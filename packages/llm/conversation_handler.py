"""
Conversational LLM Handler

Manages multi-turn conversations with Claude API, integrating with:
- ASR (Automatic Speech Recognition) for listening
- TTS (Text-to-Speech) for speaking
- Policy system for action execution

Usage:
    handler = ConversationHandler(db_conn, asr_service, tts_service)
    result = await handler.handle_doorbell_audio(audio_path, context)
"""

import os
import json
import asyncio
import numpy as np
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from dataclasses import dataclass

from .client import create_llm_client, LLMClient


@dataclass
class ConversationContext:
    """Context for a conversation session"""
    session_id: str
    camera_id: Optional[int]
    visitor_info: Dict[str, Any]
    policy_context: Dict[str, Any]
    started_ts: int
    messages: List[Dict[str, Any]]


class ConversationHandler:
    """
    Handles async multi-turn conversations with Claude API.
    
    Flow:
    1. Policy layer detects need for LLM
    2. Initiates conversation with audio/context
    3. LLM may request ASR activation for follow-up
    4. Continues until conversation completes
    5. Returns final action to policy layer
    """
    
    def __init__(
        self, 
        conn,
        asr_service=None,
        tts_service=None,
        llm_client: Optional[LLMClient] = None,
        llm_provider: str = "vicuna",
        llm_config: Optional[Dict[str, Any]] = None,
        voiceprint_service=None
    ):
        """
        Initialize conversation handler.
        
        Args:
            conn: Database connection
            asr_service: ASR service instance (optional)
            tts_service: TTS service instance (optional)
            llm_client: Pre-configured LLM client (optional)
            llm_provider: LLM provider if client not provided ("vicuna", "claude", "openai")
            llm_config: Configuration for LLM provider
                For Vicuna: {"base_url": "http://localhost:8000", "model": "vicuna-13b-v1.5"}
                For Claude: {"api_key": "sk-ant-..."}
                For OpenAI: {"api_key": "sk-...", "model": "gpt-4"}
            voiceprint_service: Voiceprint service instance (optional, for speaker identification)
        """
        self.conn = conn
        self.asr = asr_service
        self.tts = tts_service
        self.voiceprint = voiceprint_service
        
        # Initialize LLM client
        if llm_client:
            self.client = llm_client
        else:
            llm_config = llm_config or {}
            
            # Set defaults for Vicuna
            if llm_provider == "vicuna":
                llm_config.setdefault("base_url", os.getenv("VICUNA_BASE_URL", "http://localhost:8000"))
                llm_config.setdefault("model", os.getenv("VICUNA_MODEL", "vicuna-13b-v1.5"))
            
            self.client = create_llm_client(llm_provider, **llm_config)
        
        # Conversation state
        self.active_conversations: Dict[str, ConversationContext] = {}
    
    async def handle_doorbell_audio(
        self,
        audio_path: str,
        context: Dict[str, Any],
        transcribe_fn: Optional[Callable] = None,
        enable_voiceprint: bool = True
    ) -> Dict[str, Any]:
        """
        Handle doorbell audio with multi-turn conversation support.
        
        Args:
            audio_path: Path to audio file
            context: Policy context (camera_id, visitor_info, etc.)
            transcribe_fn: Optional async function to transcribe audio
            enable_voiceprint: Whether to attempt speaker identification
            
        Returns:
            Dict with action to take and conversation summary
        """
        # Create conversation session
        session_id = self._create_session(context)
        
        # Optional: Identify speaker via voiceprint
        speaker_info = None
        if enable_voiceprint and self.voiceprint:
            speaker_info = await self.match_speaker(
                audio_path,
                camera_id=context.get('camera_id'),
                session_id=session_id
            )
            
            if speaker_info:
                # Add speaker info to context
                context['speaker_match'] = speaker_info
                print(f"[VOICEPRINT] Matched speaker: {speaker_info['trusted_name']} "
                      f"({speaker_info['confidence_percent']}% confidence)")
        
        # Transcribe audio
        if transcribe_fn:
            transcript = await transcribe_fn(audio_path)
        else:
            # Fallback to basic transcription
            transcript = await self._transcribe_audio(audio_path)
        
        # Start conversation
        result = await self._converse(
            session_id,
            transcript,
            context
        )
        
        # Add speaker info to result
        if speaker_info:
            result['speaker_match'] = speaker_info
        
        # Clean up session
        self._complete_session(session_id, result)
        
        return result
    
    async def _converse(
        self,
        session_id: str,
        initial_message: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Main conversation loop - handles multi-turn interaction.
        
        Returns when LLM provides final action or conversation times out.
        """
        conversation = self.active_conversations[session_id]
        
        # Build initial message
        conversation.messages.append({
            "role": "user",
            "content": self._build_initial_prompt(initial_message, context)
        })
        
        # Conversation loop - continues until LLM signals completion
        max_turns = 10  # Safety limit
        turn_count = 0
        
        while turn_count < max_turns:
            turn_count += 1
            
            # Call LLM API
            response = await self.client.create_message(
                messages=conversation.messages,
                tools=self._get_tools(),
                system=self._get_system_prompt(),
                max_tokens=2048
            )
            
            # Add assistant response to conversation
            conversation.messages.append({
                "role": "assistant",
                "content": response.content
            })
            
            # Process response
            result = await self._process_response(session_id, response)
            
            # Check if conversation is complete
            if result.get("status") == "complete":
                return result
            
            # If awaiting ASR, wait for it
            if result.get("status") == "awaiting_user":
                # ASR will call back with user response
                user_response = await self._wait_for_user_response(
                    session_id,
                    timeout=result.get("timeout", 30)
                )
                
                if user_response:
                    # Add user response to conversation
                    conversation.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": result["tool_use_id"],
                            "content": json.dumps({
                                "transcript": user_response,
                                "success": True
                            })
                        }]
                    })
                    # Continue loop
                else:
                    # Timeout - inform LLM
                    conversation.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": result["tool_use_id"],
                            "content": json.dumps({
                                "error": "User did not respond within timeout",
                                "success": False
                            })
                        }]
                    })
                    # Continue loop - let LLM decide what to do
        
        # Max turns reached
        return {
            "status": "timeout",
            "action": "no_action",
            "summary": "Conversation exceeded maximum turns"
        }
    
    async def _process_response(
        self,
        session_id: str,
        response
    ) -> Dict[str, Any]:
        """
        Process Claude's response - handle tool calls or completion.
        """
        conversation = self.active_conversations[session_id]
        
        # Check for tool use
        for block in response.content:
            if block.type == "tool_use":
                return await self._handle_tool_call(
                    session_id,
                    block.name,
                    block.input,
                    block.id
                )
        
        # No tool use - check if LLM provided final response
        text_content = ""
        for block in response.content:
            if block.type == "text":
                text_content += block.text
        
        # If response indicates completion, return action
        if "complete" in text_content.lower() or "done" in text_content.lower():
            return {
                "status": "complete",
                "action": self._extract_action(text_content),
                "summary": text_content
            }
        
        # Otherwise, continue conversation
        return {"status": "continue"}
    
    async def _handle_tool_call(
        self,
        session_id: str,
        tool_name: str,
        params: Dict[str, Any],
        tool_use_id: str
    ) -> Dict[str, Any]:
        """
        Execute tool requested by LLM.
        """
        conversation = self.active_conversations[session_id]
        
        if tool_name == "activate_asr":
            # Speak the question first
            if self.tts and "question" in params:
                await self.tts.speak(params["question"])
            
            # Return status to wait for ASR
            return {
                "status": "awaiting_user",
                "tool_use_id": tool_use_id,
                "timeout": params.get("timeout_seconds", 30)
            }
        
        elif tool_name == "speak_to_visitor":
            # Use TTS
            if self.tts:
                await self.tts.speak(params["message"])
            
            # Add tool result to conversation
            conversation.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps({"success": True, "spoken": params["message"]})
                }]
            })
            
            return {"status": "continue"}
        
        elif tool_name == "execute_action":
            # Execute policy action (unlock door, send alert, etc.)
            action_result = await self._execute_policy_action(
                params["action"],
                params.get("parameters", {})
            )
            
            # Return completion
            return {
                "status": "complete",
                "action": params["action"],
                "action_result": action_result,
                "summary": f"Executed action: {params['action']}"
            }
        
        elif tool_name == "query_policy_context":
            # Get additional context from policy/scene systems
            context_data = await self._get_policy_context(params)
            
            # Add to conversation
            conversation.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(context_data)
                }]
            })
            
            return {"status": "continue"}
        
        elif tool_name == "reclassify_visitor":
            # Reclassify visitor intent based on conversation
            event_id = conversation.policy_context.get("event_id")
            new_intent = params.get("intent")
            confidence = params.get("confidence", 0.95)
            reason = params.get("reason", "LLM conversation reclassification")
            
            if not event_id:
                # No event to reclassify
                conversation.messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps({
                            "success": False,
                            "error": "No event_id in context"
                        })
                    }]
                })
                return {"status": "continue"}
            
            # Import reclassify service
            try:
                # Import from services if available (policy server context)
                import sys
                import os
                central_path = os.path.join(os.path.dirname(__file__), '..', '..', 'central', 'policy-server')
                if os.path.exists(central_path) and central_path not in sys.path:
                    sys.path.insert(0, central_path)
                
                from services import reclassify_visitor_intent
                
                # Add evidence based on LLM understanding
                additional_evidence = params.get("additional_evidence", [])
                
                result = reclassify_visitor_intent(
                    conn=self.conn,
                    event_id=event_id,
                    additional_evidence=additional_evidence,
                    override_intent=new_intent,
                    override_confidence=confidence,
                    reason=reason,
                    reclassified_by="llm"
                )
                
                conversation.messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(result)
                    }]
                })
                
                return {"status": "continue"}
                
            except ImportError:
                # Fallback: direct database update
                try:
                    self.conn.execute("""
                        UPDATE visitor_events
                        SET intent_inferred = ?,
                            intent_confidence = ?,
                            updated_ts = ?
                        WHERE event_id = ?
                    """, (new_intent, confidence, int(datetime.now().timestamp()), event_id))
                    self.conn.commit()
                    
                    conversation.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps({
                                "success": True,
                                "event_id": event_id,
                                "new_intent": new_intent,
                                "confidence": confidence,
                                "method": "direct_update"
                            })
                        }]
                    })
                    
                    return {"status": "continue"}
                    
                except Exception as e:
                    conversation.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps({
                                "success": False,
                                "error": str(e)
                            })
                        }]
                    })
                    return {"status": "continue"}
        
        else:
            # Unknown tool
            conversation.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps({"error": f"Unknown tool: {tool_name}"})
                }]
            })
            return {"status": "continue"}
    
    async def _wait_for_user_response(
        self,
        session_id: str,
        timeout: int
    ) -> Optional[str]:
        """
        Wait for ASR to capture user response.
        
        Returns transcript or None if timeout.
        """
        if not self.asr:
            return None
        
        # Create future for ASR result
        future = asyncio.Future()
        
        # Activate ASR with callback
        async def on_transcript(transcript: str):
            if not future.done():
                future.set_result(transcript)
        
        await self.asr.activate(
            timeout=timeout,
            callback=on_transcript
        )
        
        # Wait for result or timeout
        try:
            result = await asyncio.wait_for(future, timeout=timeout + 1)
            return result
        except asyncio.TimeoutError:
            return None
    
    def _get_tools(self) -> List[Dict[str, Any]]:
        """
        Define tools available to Claude.
        """
        return [
            {
                "name": "activate_asr",
                "description": "Activate ASR to listen for user's spoken response. Use when you need clarification or additional information from the visitor.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Question to ask the visitor (will be spoken via TTS)"
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "How long to wait for response (default 30)",
                            "default": 30
                        }
                    },
                    "required": ["question"]
                }
            },
            {
                "name": "speak_to_visitor",
                "description": "Speak a message to the visitor via TTS without waiting for response.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message to speak"
                        }
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "execute_action",
                "description": "Execute a policy action (unlock door, send alert, etc.) and complete the conversation.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["unlock_door", "send_alert", "deny_access", "no_action"],
                            "description": "Action to execute"
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Action-specific parameters",
                            "default": {}
                        }
                    },
                    "required": ["action"]
                }
            },
            {
                "name": "query_policy_context",
                "description": "Query additional context from policy/scene systems (trusted faces, recent visits, etc.)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "enum": ["trusted_faces", "recent_visits", "active_events", "quiet_hours"],
                            "description": "Type of context to query"
                        }
                    },
                    "required": ["query_type"]
                }
            },
            {
                "name": "reclassify_visitor",
                "description": "Reclassify visitor intent based on information learned during conversation. Use when visitor provides information that changes their classification (e.g., unknown person states they have a delivery).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "enum": [
                                "delivery_arriving",
                                "delivery_departing",
                                "trusted_visitor",
                                "solicitor",
                                "maintenance",
                                "emergency",
                                "friend_family",
                                "unknown"
                            ],
                            "description": "New intent classification based on conversation"
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence in new classification (0.0-1.0)",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "default": 0.95
                        },
                        "reason": {
                            "type": "string",
                            "description": "Explanation for reclassification"
                        },
                        "additional_evidence": {
                            "type": "array",
                            "description": "Optional additional evidence items to support reclassification",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {"type": "string"},
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                    "confidence": {"type": "number"}
                                }
                            },
                            "default": []
                        }
                    },
                    "required": ["intent", "reason"]
                }
            }
        ]
    
    def _get_system_prompt(self) -> str:
        """
        System prompt for LLM.
        """
        return """You are an AI assistant integrated into a smart doorbell system (echoBell).

Your role:
- Analyze doorbell interactions (audio transcripts, visitor context)
- Ask clarifying questions when needed (use activate_asr tool)
- Reclassify visitor intent based on conversation (use reclassify_visitor tool)
- Make decisions about access control
- Execute appropriate actions (unlock, alert, deny)

Guidelines:
- Be conversational and friendly
- Ask for clarification when uncertain
- Prioritize security (deny if suspicious)
- Use quiet hours and scheduled events context
- Reclassify visitors when they provide identifying information (e.g., "I have a package" → delivery_arriving)
- Complete with execute_action when decision is made

Available actions:
- unlock_door: Grant access
- send_alert: Notify homeowner
- deny_access: Politely decline
- no_action: Just log the interaction

Use tools to gather context, reclassify visitors, and interact with them.

When using tools, respond with JSON format:
{"tool": "tool_name", "parameters": {...}}
"""
    
    def _build_initial_prompt(
        self,
        transcript: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Build initial user message with transcript and context.
        """
        speaker_info = context.get('speaker_match')
        speaker_line = ""
        
        if speaker_info:
            speaker_line = f"\n- Speaker: {speaker_info['trusted_name']} ({speaker_info['confidence_percent']}% match)"
        
        return f"""Doorbell Interaction:

Transcript: "{transcript}"{speaker_line}

Context:
- Camera: {context.get('camera_id', 'unknown')}
- Visitor: {context.get('visitor_info', {})}
- Time: {datetime.now().isoformat()}
- Scene: {context.get('scene_context', 'unknown')}

Please analyze this interaction and determine the appropriate action. Ask clarifying questions if needed."""
    
    def _create_session(self, context: Dict[str, Any]) -> str:
        """Create conversation session."""
        import uuid
        session_id = str(uuid.uuid4())
        
        self.active_conversations[session_id] = ConversationContext(
            session_id=session_id,
            camera_id=context.get('camera_id'),
            visitor_info=context.get('visitor_info', {}),
            policy_context=context,
            started_ts=int(datetime.now().timestamp()),
            messages=[]
        )
        
        # Save to database
        self.conn.execute(
            """
            INSERT INTO llm_conversations (session_id, camera_id, started_ts, state, context_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                context.get('camera_id'),
                int(datetime.now().timestamp()),
                'active',
                json.dumps(context)
            )
        )
        self.conn.commit()
        
        return session_id
    
    def _complete_session(self, session_id: str, result: Dict[str, Any]):
        """Mark conversation as complete."""
        conversation = self.active_conversations.get(session_id)
        if not conversation:
            return
        
        # Update database
        self.conn.execute(
            """
            UPDATE llm_conversations
            SET completed_ts = ?, state = ?, messages_json = ?
            WHERE session_id = ?
            """,
            (
                int(datetime.now().timestamp()),
                result.get('status', 'complete'),
                json.dumps(conversation.messages),
                session_id
            )
        )
        self.conn.commit()
        
        # Clean up
        del self.active_conversations[session_id]
    
    async def _transcribe_audio(self, audio_path: str) -> str:
        """
        Fallback transcription (override with real ASR).
        """
        # This would use your actual ASR service
        # For now, return placeholder
        return "[Audio transcription not implemented]"
    
    async def fetch_voiceprint_from_edge(
        self,
        camera_id: int,
        audio_path: str,
        model_name: str = "speechbrain_ecapa"
    ) -> Optional[np.ndarray]:
        """
        Fetch voiceprint embedding from edge server.
        
        Makes HTTP request to edge server running SpeechBrain to extract
        speaker embedding from audio file.
        
        Args:
            camera_id: Edge camera/server ID
            audio_path: Path to audio file on edge server
            model_name: SpeechBrain model to use (e.g., "speechbrain_ecapa")
            
        Returns:
            Voiceprint embedding as numpy array, or None if failed
        """
        # Import here to avoid circular dependency
        from packages.data.camera_service import CameraService
        
        # Get edge server URL from camera config
        camera = CameraService.get_camera(self.conn, camera_id)
        if not camera:
            return None
        
        edge_url = camera.get('edge_url')
        if not edge_url:
            return None
        
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                # Call edge server's voiceprint extraction endpoint
                async with session.post(
                    f"{edge_url}/api/voiceprint/extract",
                    json={
                        "audio_path": audio_path,
                        "model_name": model_name
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.json()
                    
                    # Convert embedding list to numpy array
                    embedding = np.array(data['embedding'], dtype=np.float32)
                    return embedding
        
        except Exception as e:
            print(f"[ERROR] Failed to fetch voiceprint from edge {camera_id}: {e}")
            return None
    
    async def match_speaker(
        self,
        audio_path: str,
        camera_id: Optional[int] = None,
        model_name: str = "speechbrain_ecapa",
        threshold: float = 0.75,
        session_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Match speaker in audio file against stored voiceprints.
        
        Args:
            audio_path: Path to audio file
            camera_id: Optional camera ID (used to fetch from edge server)
            model_name: Voiceprint model name
            threshold: Matching threshold (0-1)
            session_id: Optional conversation session ID for logging
            
        Returns:
            Match result with trusted_id, name, and confidence, or None if no match
        """
        if not self.voiceprint:
            return None
        
        # Fetch voiceprint embedding from edge server
        if camera_id:
            embedding = await self.fetch_voiceprint_from_edge(
                camera_id,
                audio_path,
                model_name
            )
        else:
            # Fallback: extract locally (requires SpeechBrain installed)
            embedding = await self._extract_voiceprint_local(audio_path, model_name)
        
        if embedding is None:
            return None
        
        # Match against database
        from packages.data.voiceprint_service import VoiceprintService
        
        matches = VoiceprintService.match_voiceprint(
            self.conn,
            embedding=embedding,
            model_name=model_name,
            threshold=threshold,
            top_k=1
        )
        
        if not matches:
            # Log failed match attempt
            VoiceprintService.log_match_attempt(
                self.conn,
                confidence_score=0.0,
                threshold_used=threshold,
                model_name=model_name,
                session_id=session_id,
                camera_id=camera_id
            )
            return None
        
        best_match = matches[0]
        
        # Log successful match
        VoiceprintService.log_match_attempt(
            self.conn,
            confidence_score=best_match.confidence,
            threshold_used=threshold,
            model_name=model_name,
            matched_trusted_id=best_match.trusted_id,
            session_id=session_id,
            camera_id=camera_id
        )
        
        return {
            "trusted_id": best_match.trusted_id,
            "trusted_name": best_match.trusted_name,
            "confidence": best_match.confidence,
            "confidence_percent": round(best_match.confidence * 100, 1)
        }
    
    async def _extract_voiceprint_local(
        self,
        audio_path: str,
        model_name: str
    ) -> Optional[np.ndarray]:
        """
        Extract voiceprint locally (requires SpeechBrain installed).
        
        This is a fallback if edge server is not available.
        """
        try:
            # This would use SpeechBrain locally
            # For now, return None (edge server should be used)
            return None
        except Exception:
            return None
    
    async def store_voiceprint(
        self,
        audio_path: str,
        trusted_id: int,
        camera_id: Optional[int] = None,
        model_name: str = "speechbrain_ecapa",
        quality_score: float = 1.0,
        audio_duration_sec: Optional[float] = None,
        notes: Optional[str] = None
    ) -> Optional[int]:
        """
        Store a voiceprint for a trusted person.
        
        Fetches embedding from edge server and stores in database.
        
        Args:
            audio_path: Path to audio file
            trusted_id: ID of trusted person
            camera_id: Camera/edge server ID
            model_name: Voiceprint model name
            quality_score: Quality of audio sample (0-1)
            audio_duration_sec: Length of audio sample
            notes: Optional metadata
            
        Returns:
            voiceprint_id of stored voiceprint, or None if failed
        """
        if not self.voiceprint:
            return None
        
        # Fetch embedding from edge server
        if camera_id:
            embedding = await self.fetch_voiceprint_from_edge(
                camera_id,
                audio_path,
                model_name
            )
        else:
            embedding = await self._extract_voiceprint_local(audio_path, model_name)
        
        if embedding is None:
            return None
        
        # Store in database
        from packages.data.voiceprint_service import VoiceprintService
        
        voiceprint_id = VoiceprintService.create_voiceprint(
            self.conn,
            trusted_id=trusted_id,
            embedding=embedding,
            model_name=model_name,
            quality_score=quality_score,
            camera_id=camera_id,
            audio_duration_sec=audio_duration_sec,
            notes=notes
        )
        
        return voiceprint_id
    
    async def _execute_policy_action(
        self,
        action: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a policy action.
        
        This integrates with your existing PolicyExecutor.
        """
        # Import here to avoid circular dependency
        from packages.policy.executor import PolicyExecutor
        
        executor = PolicyExecutor(self.conn)
        
        # Convert LLM action to policy action format
        if action == "unlock_door":
            await executor.execute_actions([
                {"type": "unlock", **parameters}
            ], {})
        elif action == "send_alert":
            await executor.execute_actions([
                {"type": "telegram", "message": parameters.get("message", "Visitor at door")}
            ], {})
        # ... other actions
        
        return {"success": True, "action": action}
    
    async def _get_policy_context(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query policy/scene context.
        """
        query_type = params.get("query_type")
        
        if query_type == "trusted_faces":
            # Query trusted faces database
            rows = self.conn.execute(
                "SELECT name, relationship FROM trusted_faces WHERE enabled = 1"
            ).fetchall()
            return {
                "trusted_faces": [{"name": r[0], "relationship": r[1]} for r in rows]
            }
        
        elif query_type == "quiet_hours":
            # Query quiet hours
            from packages.data.quiet_hours_service import QuietHoursService
            is_quiet = QuietHoursService.is_quiet_time(self.conn)
            active = QuietHoursService.get_active_quiet_hours(self.conn)
            return {
                "is_quiet_hours": is_quiet,
                "active_quiet_hours": [
                    {"name": qh.name, "start": qh.start_time, "end": qh.end_time}
                    for qh in active
                ]
            }
        
        # ... other context queries
        
        return {}
    
    def _extract_action(self, text: str) -> str:
        """
        Extract action from LLM text response.
        """
        text_lower = text.lower()
        
        if "unlock" in text_lower:
            return "unlock_door"
        elif "alert" in text_lower or "notify" in text_lower:
            return "send_alert"
        elif "deny" in text_lower or "decline" in text_lower:
            return "deny_access"
        else:
            return "no_action"
