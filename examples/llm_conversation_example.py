"""
Example: Using ConversationHandler from Policy Layer

Shows how to integrate LLM conversations into policy evaluation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import sqlite3
from datetime import datetime
from packages.llm.conversation_handler import ConversationHandler
from packages.policy.evaluator import PolicyEvaluator


# Mock ASR service for demo
class MockASRService:
    """Mock ASR service that simulates user responses"""
    
    async def activate(self, timeout: int, callback):
        """Simulate ASR activation"""
        print(f"[ASR] Listening for {timeout} seconds...")
        
        # Simulate user response after 2 seconds
        await asyncio.sleep(2)
        
        # Simulate different responses
        simulated_responses = [
            "I'm here to deliver a package",
            "I'm a friend of the homeowner",
            "I'm here for the party",
        ]
        
        response = simulated_responses[0]  # You could randomize or prompt
        print(f"[ASR] User said: {response}")
        
        await callback(response)


# Mock TTS service for demo
class MockTTSService:
    """Mock TTS service that prints what would be spoken"""
    
    async def speak(self, message: str):
        """Simulate speaking"""
        print(f"[TTS] Speaking: {message}")
        await asyncio.sleep(1)  # Simulate speech time


async def example_doorbell_interaction():
    """
    Example: Handle doorbell audio with multi-turn conversation
    """
    # Setup
    conn = sqlite3.connect(':memory:')
    
    # Create required tables (simplified)
    conn.executescript("""
        CREATE TABLE llm_conversations (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            camera_id INTEGER,
            started_ts INTEGER,
            completed_ts INTEGER,
            state TEXT,
            context_json TEXT,
            messages_json TEXT
        );
        
        CREATE TABLE quiet_hours (
            id INTEGER PRIMARY KEY,
            name TEXT,
            weekday INTEGER,
            start_time TEXT,
            end_time TEXT,
            enabled INTEGER
        );
    """)
    
    # Initialize services
    asr = MockASRService()
    tts = MockTTSService()
    
    # Initialize conversation handler with Vicuna
    # NOTE: Vicuna server must be running (e.g., via FastChat)
    # Start with: python -m fastchat.serve.controller
    #             python -m fastchat.serve.model_worker --model-path lmsys/vicuna-13b-v1.5
    #             python -m fastchat.serve.openai_api_server
    
    handler = ConversationHandler(
        conn=conn,
        asr_service=asr,
        tts_service=tts,
        llm_provider="vicuna",
        llm_config={
            "base_url": "http://localhost:8000",
            "model": "vicuna-13b-v1.5"
        }
    )
    
    # Simulate doorbell audio transcript
    def mock_transcribe(audio_path):
        """Mock transcription"""
        return asyncio.create_task(
            asyncio.sleep(0, result="Hello, is anyone home?")
        )
    
    # Policy context
    context = {
        "camera_id": 1,
        "visitor_info": {
            "face_detected": True,
            "face_recognized": False,
            "confidence": 0.95
        },
        "scene_context": {
            "time_of_day": "afternoon",
            "is_quiet_hours": False
        },
        "timestamp": datetime.now().isoformat()
    }
    
    print("\n" + "="*60)
    print("DOORBELL INTERACTION EXAMPLE")
    print("="*60)
    
    print(f"\n[DOORBELL] Audio received from camera {context['camera_id']}")
    print(f"[DOORBELL] Visitor: {context['visitor_info']}")
    
    # Handle conversation
    print("\n[LLM] Starting conversation...")
    result = await handler.handle_doorbell_audio(
        audio_path="/path/to/audio.wav",  # Not actually used with mock
        context=context,
        transcribe_fn=mock_transcribe
    )
    
    print("\n" + "="*60)
    print("CONVERSATION RESULT")
    print("="*60)
    print(f"Status: {result.get('status')}")
    print(f"Action: {result.get('action')}")
    print(f"Summary: {result.get('summary')}")
    print()


async def example_policy_integration():
    """
    Example: Integrate LLM into policy evaluation
    
    Shows how a policy can trigger LLM conversation when needed.
    """
    
    print("\n" + "="*60)
    print("POLICY INTEGRATION EXAMPLE")
    print("="*60)
    
    # Policy that uses LLM for unknown visitors
    policy_with_llm = {
        "id": "unknown_visitor_llm",
        "name": "Unknown Visitor LLM",
        "priority": 50,
        "conditions": {
            "all": [
                {"evidence_exists": {"source": "vision", "feature": "person_detected"}},
                {"not": {"is_trusted_face": True}}
            ]
        },
        "actions": [
            {
                "type": "llm_conversation",
                "initial_greeting": "Hello! Can I help you?",
                "max_turns": 5,
                "context": {
                    "scenario": "unknown_visitor"
                }
            }
        ]
    }
    
    print("\nPolicy Definition:")
    print(f"Name: {policy_with_llm['name']}")
    print(f"Trigger: Unknown person detected")
    print(f"Action: Start LLM conversation")
    
    print("\nFlow:")
    print("1. Unknown person approaches doorbell")
    print("2. Policy evaluator triggers LLM conversation action")
    print("3. LLM asks: 'Hello! Can I help you?'")
    print("4. Visitor responds (ASR captures)")
    print("5. LLM analyzes response:")
    print("   - Delivery? → Ask for package info → Unlock gate")
    print("   - Friend? → Ask who they're visiting → Alert homeowner")
    print("   - Suspicious? → Deny access → Send alert")
    print("6. LLM executes appropriate action")
    print()


async def example_multi_turn_conversation():
    """
    Example conversation flow showing multiple turns
    """
    
    print("\n" + "="*60)
    print("MULTI-TURN CONVERSATION EXAMPLE")
    print("="*60)
    
    print("\n[Visitor] *rings doorbell*")
    print("[System] Detects unknown face")
    print()
    
    print("Turn 1:")
    print("  [LLM → TTS] 'Hello! How can I help you?'")
    print("  [ASR active, waiting for response...]")
    print("  [Visitor → ASR] 'I have a delivery'")
    print()
    
    print("Turn 2:")
    print("  [LLM → TTS] 'Great! Who is the delivery for?'")
    print("  [ASR active, waiting for response...]")
    print("  [Visitor → ASR] 'It's for John Smith'")
    print()
    
    print("Turn 3:")
    print("  [LLM checks] John Smith is homeowner")
    print("  [LLM → TTS] 'Thank you! Please leave the package at the door.'")
    print("  [LLM → Action] Send notification to homeowner")
    print("  [LLM → Action] Take photo of package")
    print("  [Conversation] COMPLETE")
    print()


if __name__ == "__main__":
    print("\n🔔 EchoBell LLM Conversation Examples\n")
    
    # Run examples
    asyncio.run(example_policy_integration())
    asyncio.run(example_multi_turn_conversation())
    
    # Uncomment to test with real API (requires ANTHROPIC_API_KEY)
    # asyncio.run(example_doorbell_interaction())
    
    print("✅ Examples complete\n")
