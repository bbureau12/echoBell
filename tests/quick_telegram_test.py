"""
Quick Telegram Test - Verify your Telegram bot configuration

This script sends a simple test message to verify your bot works.

Usage:
    $env:TELEGRAM_BOT_TOKEN = "your_token"
    $env:TELEGRAM_CHAT_ID = "your_chat_id"
    python tests/quick_telegram_test.py
"""
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from packages.integrations.telegram import load_telegram_config, TelegramNotifier


def main():
    print("="*60)
    print("Telegram Bot Configuration Test")
    print("="*60)
    
    # Check environment variables
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token:
        print("\n❌ TELEGRAM_BOT_TOKEN not set")
        print("   Set it with: $env:TELEGRAM_BOT_TOKEN = 'your_token'")
        print("   Get token from: https://t.me/BotFather")
        return 1
    
    if not chat_id:
        print("\n❌ TELEGRAM_CHAT_ID not set")
        print("   Set it with: $env:TELEGRAM_CHAT_ID = 'your_chat_id'")
        print("   Get chat ID from: https://t.me/userinfobot")
        return 1
    
    print(f"\n✅ Environment variables set")
    print(f"   Bot Token: {token[:20]}...")
    print(f"   Chat ID: {chat_id}")
    
    # Load config
    config = load_telegram_config()
    
    if not config:
        print("\n❌ Failed to load Telegram config")
        return 1
    
    if not config.enabled:
        print("\n❌ Telegram is disabled (TELEGRAM_ENABLED=false)")
        return 1
    
    print(f"\n✅ Config loaded successfully")
    print(f"   Enabled: {config.enabled}")
    print(f"   Timeout: {config.timeout_s}s")
    
    # Create notifier
    notifier = TelegramNotifier(config)
    
    # Send test message
    print(f"\n📤 Sending test message...")
    test_message = "✅ EchoBell Telegram Bot Test - Message received successfully!"
    
    success = notifier.send_message(test_message)
    
    if success:
        print(f"\n✅ SUCCESS! Message sent to Telegram")
        print(f"\n📱 Check your Telegram chat for the test message:")
        print(f"   '{test_message}'")
        print(f"\n✅ Your Telegram bot is configured correctly!")
        return 0
    else:
        print(f"\n❌ FAILED to send message")
        print(f"\n💡 Troubleshooting:")
        print(f"   1. Verify bot token is correct")
        print(f"   2. Verify chat ID is correct")
        print(f"   3. Send /start to your bot in Telegram")
        print(f"   4. Make sure bot is not blocked")
        print(f"\n   Test manually:")
        print(f"   curl https://api.telegram.org/bot{token[:20]}.../getMe")
        return 1


if __name__ == '__main__':
    sys.exit(main())
