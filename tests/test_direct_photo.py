"""Direct test of Telegram photo sending"""
from packages.integrations.telegram import load_telegram_config, TelegramNotifier
import os

# Test configuration
photo_path = "data/edge_images/cam1_1769480091.jpg"
caption = "🧪 Direct Photo Test from Python"

print("=" * 70)
print("Direct Telegram Photo Test")
print("=" * 70)

# Check file exists
print(f"\n1. Checking file...")
print(f"   Path: {photo_path}")
print(f"   Exists: {os.path.exists(photo_path)}")

if not os.path.exists(photo_path):
    # Try absolute path
    abs_path = os.path.abspath(photo_path)
    print(f"   Trying absolute: {abs_path}")
    print(f"   Exists: {os.path.exists(abs_path)}")
    if os.path.exists(abs_path):
        photo_path = abs_path
    else:
        print("\n❌ File not found! Cannot test.")
        exit(1)

file_size = os.path.getsize(photo_path)
print(f"   Size: {file_size:,} bytes")

# Load config
print(f"\n2. Loading Telegram config...")
config = load_telegram_config()

if not config or not config.enabled:
    print("❌ Telegram not configured!")
    exit(1)

print(f"   ✓ Bot token: {config.token[:20]}...")
print(f"   ✓ Chat ID: {config.chat_id}")

# Send photo
print(f"\n3. Sending photo...")
print(f"   Caption: {caption}")

notifier = TelegramNotifier(config)
success = notifier.send_photo(photo_path, caption=caption)

if success:
    print(f"\n✅ SUCCESS! Photo sent to Telegram!")
    print(f"\n📱 Check your Telegram chat")
    print(f"   You should see:")
    print(f"   - The photo from {photo_path}")
    print(f"   - Caption: {caption}")
else:
    print(f"\n❌ FAILED to send photo")
    print(f"\nTroubleshooting:")
    print(f"  1. Check bot token is valid")
    print(f"  2. Check chat ID is correct")  
    print(f"  3. Check file is a valid image")
    print(f"  4. Check internet connection")
