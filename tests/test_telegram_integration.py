"""
Integration test for Telegram notifications.

This test sends an actual message to your configured Telegram bot to verify
the integration is working end-to-end.

Setup:
    Set environment variables:
    - TELEGRAM_BOT_TOKEN: Your bot token from @BotFather
    - TELEGRAM_CHAT_ID: Your chat ID (get from @userinfobot)
    - TELEGRAM_ENABLED: "true" to enable (optional, defaults to true)

Usage:
    pytest tests/test_telegram_integration.py -v -s
"""

import os
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.integrations.telegram import load_telegram_config, TelegramNotifier


class TestTelegramIntegration:
    """Integration tests for Telegram bot notifications."""
    
    def test_send_integration_test_message(self):
        """
        Send a test message to Telegram to verify the integration works.
        
        This will send an actual message to your configured Telegram chat.
        Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
        """
        # Load config from environment
        config = load_telegram_config()
        
        if config is None:
            pytest.skip(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                "environment variables to run this test."
            )
        
        if not config.enabled:
            pytest.skip("Telegram is disabled (TELEGRAM_ENABLED=false)")
        
        # Create notifier
        notifier = TelegramNotifier(config)
        
        # Send test message
        success = notifier.send_message("✅ Integration test success!")
        
        assert success, "Failed to send Telegram message"
        print("\n✓ Successfully sent test message to Telegram")
    
    def test_config_loading_from_env(self):
        """Test that config loads correctly from environment variables."""
        config = load_telegram_config()
        
        if config is None:
            pytest.skip("Telegram not configured")
        
        assert config.token is not None
        assert config.chat_id is not None
        assert isinstance(config.enabled, bool)
        assert isinstance(config.timeout_s, int)
        
        print(f"\n✓ Config loaded: enabled={config.enabled}, timeout={config.timeout_s}s")
    
    def test_disabled_config_does_not_send(self):
        """Test that disabled config does not send messages."""
        from packages.integrations.telegram import TelegramConfig
        
        # Create a disabled config
        config = TelegramConfig(
            token="fake_token",
            chat_id="fake_chat_id",
            enabled=False
        )
        
        notifier = TelegramNotifier(config)
        
        # Should return False without attempting to send
        success = notifier.send_message("This should not be sent")
        
        assert success is False
        print("\n✓ Disabled config correctly skips sending")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
