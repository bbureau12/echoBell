#!/usr/bin/env python3
"""
Echonet Integration Test Script

Tests auto-discovery and registration with Echonet instances.
"""

import asyncio
import sys
import time
from echonet_service import (
    EchonetRegistrationService,
    ZEROCONF_AVAILABLE
)

async def test_discovery():
    """Test Echonet discovery and registration"""
    
    print("=" * 70)
    print("  Echonet Discovery & Registration Test")
    print("=" * 70)
    print()
    
    # Check dependencies
    print("1. Checking dependencies...")
    if not ZEROCONF_AVAILABLE:
        print("   ❌ zeroconf not installed")
        print("   Install with: pip install zeroconf")
        return False
    print("   ✓ zeroconf available")
    print()
    
    # Initialize service
    print("2. Initializing Echonet service...")
    service = EchonetRegistrationService(
        target_name="echobell-test",
        base_url="http://test-server.local:8000",
        wake_phrases=["echobell", "hey echo"],
        api_key="dontgiveitupluffy"
    )
    print("   ✓ Service initialized")
    print()
    
    # Start discovery
    print("3. Starting mDNS discovery (_echonet._tcp.local.)...")
    service.start_discovery()
    print("   ✓ Discovery started")
    print()
    
    # Wait for discovery
    print("4. Listening for Echonet instances (10 seconds)...")
    for i in range(10, 0, -1):
        discovered = len(service.listener.instances) if service.listener else 0
        print(f"   {i}s remaining... ({discovered} instance(s) discovered)", end="\r")
        await asyncio.sleep(1)
    print()
    print()
    
    # Check results
    if not service.listener:
        print("   ❌ Listener not started")
        return False
    
    discovered = service.listener.instances
    print(f"5. Discovery complete: {len(discovered)} instance(s) found")
    print()
    
    if len(discovered) == 0:
        print("   ❌ No Echonet instances discovered")
        print()
        print("   Troubleshooting:")
        print("   - Is Echonet running?")
        print("   - Are you on the same network?")
        print("   - Is mDNS enabled on your network?")
        print("   - Try: dns-sd -B _echonet._tcp (macOS/Linux)")
        service.stop_discovery()
        return False
    
    # List discovered instances
    for name, instance in discovered.items():
        print(f"   ✓ {instance.display_name}")
        print(f"     URL: {instance.base_url}")
        if instance.zone:
            print(f"     Zone: {instance.zone}")
        if instance.subzone:
            print(f"     Subzone: {instance.subzone}")
        if instance.version:
            print(f"     Version: {instance.version}")
        print()
    
    # Test registration (dry run - won't actually register)
    print("6. Testing registration (checking connectivity)...")
    print("   Note: Not actually registering to avoid conflicts")
    print()
    
    import httpx
    for name, instance in discovered.items():
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Just check health endpoint
                response = await client.get(f"{instance.base_url}/health")
                if response.status_code == 200:
                    print(f"   ✓ {instance.name}: Reachable ({instance.base_url})")
                else:
                    print(f"   ⚠️  {instance.name}: HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ {instance.name}: {str(e)}")
    
    print()
    
    # Cleanup
    print("7. Stopping discovery...")
    service.stop_discovery()
    print("   ✓ Stopped")
    print()
    
    print("=" * 70)
    print("  Test Complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Set environment variables:")
    print("     export POLICY_SERVER_BASE_URL=http://your-server:8000")
    print("     export ECHONET_API_KEY=dontgiveitupluffy")
    print()
    print("  2. Start policy server:")
    print("     uvicorn server:app --reload")
    print()
    print("  3. Check health:")
    print("     curl http://localhost:8000/health | jq .echonet")
    print()
    
    return True


if __name__ == "__main__":
    result = asyncio.run(test_discovery())
    sys.exit(0 if result else 1)
