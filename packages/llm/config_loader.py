"""
Configuration loader for LLM settings

Loads LLM configuration from TOML file or environment variables.
"""

import os
import tomli
from typing import Dict, Any, Optional
from pathlib import Path


def load_llm_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load LLM configuration from file or environment variables.
    
    Args:
        config_path: Path to TOML config file (optional)
        
    Returns:
        Configuration dictionary
        
    Priority:
        1. Environment variables (VICUNA_BASE_URL, etc.)
        2. Config file
        3. Defaults
    """
    # Default config path
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "llm_config.toml"
        )
    
    # Load from file if exists
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "rb") as f:
            config = tomli.load(f)
    
    # Override with environment variables
    provider = os.getenv("LLM_PROVIDER", config.get("llm", {}).get("provider", "vicuna"))
    
    # Build final config
    llm_config = {
        "provider": provider
    }
    
    # Provider-specific settings
    if provider == "vicuna":
        vicuna_config = config.get("llm", {}).get("vicuna", {})
        llm_config["vicuna"] = {
            "base_url": os.getenv("VICUNA_BASE_URL", vicuna_config.get("base_url", "http://localhost:8000")),
            "model": os.getenv("VICUNA_MODEL", vicuna_config.get("model", "vicuna-13b-v1.5")),
            "temperature": float(os.getenv("VICUNA_TEMPERATURE", vicuna_config.get("temperature", 0.7))),
            "max_tokens": int(os.getenv("VICUNA_MAX_TOKENS", vicuna_config.get("max_tokens", 2048)))
        }
    
    elif provider == "claude":
        claude_config = config.get("llm", {}).get("claude", {})
        llm_config["claude"] = {
            "api_key": os.getenv("ANTHROPIC_API_KEY", claude_config.get("api_key", "")),
            "model": os.getenv("CLAUDE_MODEL", claude_config.get("model", "claude-3-5-sonnet-20241022"))
        }
    
    elif provider == "openai":
        openai_config = config.get("llm", {}).get("openai", {})
        llm_config["openai"] = {
            "api_key": os.getenv("OPENAI_API_KEY", openai_config.get("api_key", "")),
            "model": os.getenv("OPENAI_MODEL", openai_config.get("model", "gpt-4"))
        }
    
    # Conversation settings
    conv_config = config.get("conversation", {})
    llm_config["conversation"] = {
        "max_turns": int(os.getenv("CONVERSATION_MAX_TURNS", conv_config.get("max_turns", 10))),
        "asr_timeout": int(os.getenv("ASR_TIMEOUT", conv_config.get("asr_timeout", 30))),
        "enable_tool_calling": os.getenv("ENABLE_TOOL_CALLING", str(conv_config.get("enable_tool_calling", True))).lower() == "true"
    }
    
    # Network settings
    net_config = config.get("network", {})
    llm_config["network"] = {
        "timeout": int(os.getenv("LLM_TIMEOUT", net_config.get("timeout", 60))),
        "retry_attempts": int(os.getenv("LLM_RETRY_ATTEMPTS", net_config.get("retry_attempts", 3))),
        "retry_delay": int(os.getenv("LLM_RETRY_DELAY", net_config.get("retry_delay", 2)))
    }
    
    return llm_config


def create_handler_from_config(
    conn,
    asr_service=None,
    tts_service=None,
    config_path: Optional[str] = None
):
    """
    Create ConversationHandler from config file.
    
    Args:
        conn: Database connection
        asr_service: ASR service instance
        tts_service: TTS service instance
        config_path: Path to config file (optional)
        
    Returns:
        ConversationHandler instance
        
    Example:
        handler = create_handler_from_config(db, asr, tts)
    """
    from .conversation_handler import ConversationHandler
    
    config = load_llm_config(config_path)
    provider = config["provider"]
    
    return ConversationHandler(
        conn=conn,
        asr_service=asr_service,
        tts_service=tts_service,
        llm_provider=provider,
        llm_config=config.get(provider, {})
    )


if __name__ == "__main__":
    # Test config loading
    config = load_llm_config()
    
    print("LLM Configuration:")
    print(f"Provider: {config['provider']}")
    print(f"\nVicuna:")
    print(f"  Base URL: {config['vicuna']['base_url']}")
    print(f"  Model: {config['vicuna']['model']}")
    print(f"\nConversation:")
    print(f"  Max Turns: {config['conversation']['max_turns']}")
    print(f"  ASR Timeout: {config['conversation']['asr_timeout']}s")
