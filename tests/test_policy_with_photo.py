"""
Standalone test: Simulate policy evaluation with photo

This test will:
1. Create evidence with photo path
2. Evaluate policy
3. Execute telegram action with photo
4. Show detailed logging
"""

import sqlite3
import asyncio
import time
from pathlib import Path

# Setup
DB_PATH = "data/echoBell.db"
PHOTO_PATH = "data/edge_images/cam1_1769480091.jpg"

print("=" * 70)
print("Policy Evaluation Test with Photo")
print("=" * 70)

# Prepare evidence
evidence = [
    {
        'source': 'vision',
        'feature': 'vehicle_present',
        'value': 'true',
        'conf': 0.95
    },
    {
        'source': 'vision',
        'feature': 'vehicle_color',
        'value': 'white',
        'conf': 0.85
    },
    {
        'source': 'vision',
        'feature': 'vehicle_type',
        'value': 'sedan',
        'conf': 0.90
    },
    {
        'source': 'vision',
        'feature': 'latest_frame_path',
        'value': PHOTO_PATH,
        'conf': 1.0
    }
]

# Context
context = {
    'camera_id': 1,
    'track_key': f'test_vehicle_{int(time.time())}',
    'track_type': 'vehicle',
    'event_id': f'test_event_{int(time.time())}',
    'timestamp': int(time.time())
}

print(f"\n📦 Evidence:")
for ev in evidence:
    print(f"   - {ev['source']}.{ev['feature']} = {ev['value']}")

print(f"\n📍 Context:")
print(f"   - camera_id: {context['camera_id']}")
print(f"   - track_key: {context['track_key']}")
print(f"   - event_id: {context['event_id']}")

print(f"\n🖼️  Photo:")
print(f"   - Path: {PHOTO_PATH}")
print(f"   - Exists: {Path(PHOTO_PATH).exists()}")

async def test():
    from packages.policy.apply import evaluate_policies
    from packages.policy.evaluator import PolicyEvaluator
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        # First, let's see which policies match
        print(f"\n🔍 Checking policy matches...")
        evaluator = PolicyEvaluator(conn=conn, use_database=True)
        matches = evaluator.evaluate_all(evidence, context)
        
        print(f"   Found {len(matches)} matching policies:")
        for match in matches:
            print(f"   - {match.policy_name} (priority {match.priority})")
        
        print(f"\n⚙️  Evaluating policies...")
        results = await evaluate_policies(
            evidence=evidence,
            context=context,
            conn=conn,
            use_database=True
        )
        
        print(f"\n✅ Evaluation complete!")
        print(f"   Total actions executed: {len(results)}")
        
        # List ALL results
        for i, result in enumerate(results, 1):
            print(f"\n   Result {i}:")
            print(f"      Policy ID: {result.get('policy_id')}")
            print(f"      Policy Name: {result.get('policy_name')}")
            print(f"      Priority: {result.get('priority')}")
            print(f"      Action Type: {result.get('action_type')}")
            print(f"      Success: {result.get('success')}")
            if result.get('error'):
                print(f"      Error: {result.get('error')}")
            if result.get('message'):
                print(f"      Message: {result.get('message')}")
        
        # Check if photo was sent
        telegram_results = [r for r in results if r.get('action_type') == 'telegram']
        if telegram_results:
            print(f"\n📱 Telegram Results:")
            for r in telegram_results:
                if r.get('success'):
                    print(f"   ✅ {r.get('policy_name')}")
                    print(f"      Message sent successfully")
                    print(f"      Check your Telegram chat!")
                else:
                    print(f"   ❌ {r.get('policy_name')}")
                    print(f"      Failed: {r.get('error')}")
        
    finally:
        conn.close()

# Run the test
asyncio.run(test())

print("\n" + "=" * 70)
print("Test Complete")
print("=" * 70)
