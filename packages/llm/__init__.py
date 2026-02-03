"""
LLM Integration Package

Handles conversational interactions with LLM backends for:
- Multi-turn doorbell conversations
- Policy clarification
- Dynamic ASR activation

Supports distributed architecture:
- LLM can run on separate GPU server
- Communication via HTTP
- Vicuna, Claude, or OpenAI backends
"""

from .conversation_handler import ConversationHandler
from .config_loader import load_llm_config, create_handler_from_config
from .client import create_llm_client, LLMClient, VicunaClient

__all__ = [
    'ConversationHandler',
    'load_llm_config',
    'create_handler_from_config',
    'create_llm_client',
    'LLMClient',
    'VicunaClient'
]
