"""
LLM Conversation Action Handler

Allows policies to initiate multi-turn conversations with the LLM when specific
conditions are met (e.g., unknown visitor, ambiguous intent, security decision needed).

Example usage in policy:
    actions:
      - type: llm_conversation
        initial_greeting: "Hello! Can I help you?"
        max_turns: 5
        enable_voiceprint: true
        context:
          scenario: "unknown_visitor"
"""
import sqlite3
import logging
from typing import Dict, Any, Optional
from ..action_handlers import register_action_handler, substitute_variables

logger = logging.getLogger(__name__)


@register_action_handler("llm_conversation")
class LLMConversationActionHandler:
    """
    Initiate multi-turn conversation with LLM.
    
    This handler enables the policy layer to delegate decision-making to the LLM
    when conditions are uncertain or require interactive clarification.
    
    The LLM can:
    - Ask follow-up questions (using activate_asr tool)
    - Speak to visitors (using speak_to_visitor tool)
    - Query additional context (using query_policy_context tool)
    - Execute final actions (using execute_action tool)
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute LLM conversation action.
        
        Args:
            action: Dict with:
                - initial_greeting: Optional greeting to start conversation
                - audio_path: Optional path to initial audio (or use context)
                - max_turns: Optional max conversation turns (default: 10)
                - enable_voiceprint: Whether to attempt speaker ID (default: True)
                - llm_provider: Optional LLM provider override (vicuna/claude/openai)
                - context: Optional additional context for LLM
            variables: Substitution variables
            context: Runtime context with camera_id, event_id, audio_path, etc.
        
        Returns:
            Dict with success status, LLM decision, and conversation summary
        """
        try:
            # Lazy import to avoid circular dependencies
            from packages.llm import ConversationHandler, load_llm_config
            
            # Get audio path (from action spec or context)
            audio_path = action.get('audio_path')
            if audio_path:
                audio_path = substitute_variables(audio_path, variables)
            if not audio_path:
                audio_path = context.get('audio_path') or variables.get('audio_path')
            
            # If no audio but initial greeting provided, simulate initial transcript
            initial_greeting = action.get('initial_greeting', '')
            if initial_greeting:
                initial_greeting = substitute_variables(initial_greeting, variables)
            
            if not audio_path and not initial_greeting:
                return {
                    'action_type': 'llm_conversation',
                    'success': False,
                    'error': 'No audio_path or initial_greeting provided'
                }
            
            # Get LLM configuration
            llm_provider = action.get('llm_provider')
            llm_config = None
            
            if not llm_provider:
                # Load from config file
                config = load_llm_config()
                llm_provider = config.get('provider', 'vicuna')
                llm_config = config.get(llm_provider, {})
            
            # Build conversation context
            conversation_context = {
                'camera_id': context.get('camera_id'),
                'event_id': context.get('event_id'),
                'track_key': context.get('track_key'),
                'visitor_info': context.get('visitor_info', {}),
                'policy_context': context.get('policy_context', {}),
                'scenario': action.get('context', {}).get('scenario', 'general'),
            }
            
            # Merge additional context from action
            if 'context' in action:
                conversation_context['policy_context'].update(action['context'])
            
            # Get optional services (if available in context)
            asr_service = context.get('asr_service')
            tts_service = context.get('tts_service')
            voiceprint_service = context.get('voiceprint_service')
            
            # Initialize conversation handler
            handler = ConversationHandler(
                conn=self.conn,
                asr_service=asr_service,
                tts_service=tts_service,
                llm_provider=llm_provider,
                llm_config=llm_config,
                voiceprint_service=voiceprint_service
            )
            
            # Handle conversation
            if audio_path:
                # Real audio interaction
                enable_voiceprint = action.get('enable_voiceprint', True)
                result = await handler.handle_doorbell_audio(
                    audio_path=audio_path,
                    context=conversation_context,
                    enable_voiceprint=enable_voiceprint
                )
            else:
                # Simulated interaction with initial greeting
                # This is useful for testing or text-based triggers
                result = await handler._converse(
                    session_id=handler._create_session(conversation_context),
                    initial_message=initial_greeting,
                    context=conversation_context
                )
            
            # Extract decision and summary
            llm_action = result.get('action', 'no_action')
            summary = result.get('summary', 'Conversation completed')
            status = result.get('status', 'complete')
            
            # Check if conversation was successful
            success = status == 'complete'
            
            # Log conversation result
            logger.info(
                f"[LLM_CONVERSATION] Camera {conversation_context.get('camera_id')}: "
                f"Action={llm_action}, Status={status}"
            )
            
            # Build response
            response = {
                'action_type': 'llm_conversation',
                'success': success,
                'llm_action': llm_action,
                'summary': summary,
                'status': status
            }
            
            # Include speaker match if available
            if 'speaker_match' in result:
                response['speaker_match'] = result['speaker_match']
            
            # Include action result if LLM executed something
            if 'action_result' in result:
                response['action_result'] = result['action_result']
            
            # Log error if failed
            if not success:
                error_msg = result.get('error', f'Conversation status: {status}')
                response['error'] = error_msg
                logger.error(f"[LLM_CONVERSATION] Failed: {error_msg}")
            
            return response
            
        except ImportError as e:
            error_msg = f"LLM package not available: {e}"
            logger.error(f"[LLM_CONVERSATION] {error_msg}")
            return {
                'action_type': 'llm_conversation',
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"LLM conversation failed: {e}"
            logger.error(f"[LLM_CONVERSATION] {error_msg}", exc_info=True)
            return {
                'action_type': 'llm_conversation',
                'success': False,
                'error': error_msg
            }
