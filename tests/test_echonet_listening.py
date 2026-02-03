#!/usr/bin/env python3
"""
Test Echonet Listening Mode Activation

Verifies that the LLM can successfully activate and deactivate
open listening mode on Echonet instances.

Usage:
    python test_echonet_listening.py --echonet-url http://192.168.1.50:8123
    
Requirements:
    - Echonet instance running and registered
    - Policy server running with Echonet discovery
    - ECHONET_API_KEY environment variable set
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
POLICY_SERVER_DIR = PROJECT_ROOT / "central" / "policy-server"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(POLICY_SERVER_DIR))

# Direct import from policy-server directory
from echonet_mode_service import EchonetModeService


async def test_listening_activation(echonet_url: str, target_name: str = "echobell"):
    """Test activating and deactivating listening mode"""
    
    service = EchonetModeService()
    
    print(f"\n{'='*60}")
    print(f"Testing Echonet Listening Mode")
    print(f"Echonet URL: {echonet_url}")
    print(f"Target Name: {target_name}")
    print(f"{'='*60}\n")
    
    # Step 1: Get current state
    print("Step 1: Getting current Echonet state...")
    state = await service.get_echonet_state(echonet_url)
    
    if not state:
        print("❌ FAILED: Could not get Echonet state")
        print("   Check that Echonet is running and API key is correct")
        return False
    
    print(f"✓ Current state retrieved")
    print(f"  Listen Mode: {state.get('listen_mode')}")
    print(f"  Target: {state.get('target_name')}")
    print(f"  Uptime: {state.get('uptime_seconds')}s")
    
    initial_mode = state.get('listen_mode')
    
    # Step 2: Activate listening mode
    print("\nStep 2: Activating open listening mode...")
    result = await service.activate_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source="test_script",
        reason="Testing LLM-requested conversation flow"
    )
    
    if not result.get('success'):
        print(f"❌ FAILED: Could not activate listening")
        print(f"   Error: {result.get('error')}")
        print(f"   Message: {result.get('message')}")
        return False
    
    print("✓ Listening mode activated")
    print(f"  Previous: {result.get('previous_mode')}")
    print(f"  New: {result.get('new_mode')}")
    
    # Step 3: Verify mode changed
    print("\nStep 3: Verifying mode change...")
    await asyncio.sleep(1)  # Give Echonet time to update
    
    state = await service.get_echonet_state(echonet_url)
    current_mode = state.get('listen_mode')
    
    if current_mode != 'open_listen':
        print(f"❌ FAILED: Mode did not change to open_listen")
        print(f"   Expected: open_listen")
        print(f"   Actual: {current_mode}")
        return False
    
    print("✓ Mode verified as open_listen")
    
    # Step 4: Wait a bit (simulate conversation)
    print("\nStep 4: Simulating conversation (5 seconds)...")
    for i in range(5, 0, -1):
        print(f"  {i}...", end='\r')
        await asyncio.sleep(1)
    print("  ✓ Conversation simulated")
    
    # Step 5: Deactivate listening
    print("\nStep 5: Deactivating listening mode...")
    result = await service.deactivate_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source="test_script",
        reason="Test conversation complete"
    )
    
    if not result.get('success'):
        print(f"❌ FAILED: Could not deactivate listening")
        print(f"   Error: {result.get('error')}")
        return False
    
    print("✓ Listening mode deactivated")
    print(f"  Previous: {result.get('previous_mode')}")
    print(f"  New: {result.get('new_mode')}")
    
    # Step 6: Verify returned to trigger mode
    print("\nStep 6: Verifying return to trigger mode...")
    await asyncio.sleep(1)
    
    state = await service.get_echonet_state(echonet_url)
    current_mode = state.get('listen_mode')
    
    if current_mode != 'trigger':
        print(f"❌ FAILED: Mode did not return to trigger")
        print(f"   Expected: trigger")
        print(f"   Actual: {current_mode}")
        return False
    
    print("✓ Mode verified as trigger")
    
    # Success
    print(f"\n{'='*60}")
    print("✅ ALL TESTS PASSED")
    print(f"{'='*60}\n")
    
    print("Summary:")
    print(f"  ✓ Successfully activated open_listen mode")
    print(f"  ✓ Successfully deactivated back to trigger mode")
    print(f"  ✓ LLM can request additional voice input from users")
    
    return True


async def test_timeout_behavior(echonet_url: str, target_name: str = "echobell"):
    """Test that Echonet auto-returns to trigger mode after timeout"""
    
    service = EchonetModeService()
    
    print(f"\n{'='*60}")
    print(f"Testing Automatic Timeout Behavior")
    print(f"{'='*60}\n")
    
    print("Activating listening mode without manual deactivation...")
    result = await service.activate_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source="test_timeout",
        reason="Testing automatic timeout"
    )
    
    if not result.get('success'):
        print("❌ Could not activate for timeout test")
        return False
    
    print("✓ Listening activated")
    print("\nWaiting 35 seconds for automatic timeout...")
    print("(Echonet default timeout is 30 seconds)")
    
    for i in range(35, 0, -1):
        print(f"  {i}s remaining...", end='\r')
        await asyncio.sleep(1)
    
    print("\n\nChecking if mode auto-returned to trigger...")
    state = await service.get_echonet_state(echonet_url)
    mode = state.get('listen_mode')
    
    if mode == 'trigger':
        print("✅ SUCCESS: Echonet auto-returned to trigger mode")
        return True
    else:
        print(f"❌ FAILED: Mode is still '{mode}' after timeout")
        print("   Manually deactivating...")
        await service.deactivate_listening(echonet_url, target_name)
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="Test Echonet listening mode activation/deactivation"
    )
    parser.add_argument(
        "--echonet-url",
        required=True,
        help="Base URL of Echonet instance (e.g., http://192.168.1.50:8123)"
    )
    parser.add_argument(
        "--target-name",
        default="echobell",
        help="Target name registered with Echonet (default: echobell)"
    )
    parser.add_argument(
        "--test-timeout",
        action="store_true",
        help="Also test automatic timeout behavior (takes 35s)"
    )
    
    args = parser.parse_args()
    
    # Check API key
    if not os.getenv("ECHONET_API_KEY"):
        print("❌ ERROR: ECHONET_API_KEY environment variable not set")
        print("   Set it to match your Echonet instance API key")
        return 1
    
    # Run activation/deactivation test
    success = await test_listening_activation(args.echonet_url, args.target_name)
    
    if not success:
        return 1
    
    # Optionally test timeout
    if args.test_timeout:
        print("\n" + "="*60)
        input("Press Enter to test timeout behavior (or Ctrl+C to skip)...")
        success = await test_timeout_behavior(args.echonet_url, args.target_name)
        if not success:
            return 1
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
