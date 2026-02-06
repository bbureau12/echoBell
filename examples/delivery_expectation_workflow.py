#!/usr/bin/env python3
"""
Delivery Expectation Workflow Example

Demonstrates the complete flow for temporal context-based intent overrides:
1. User creates delivery expectation via voice or API
2. Unknown vehicle arrives
3. Policy overrides classification based on temporal context
4. Reclassification action updates intent
"""

import sqlite3
import time
import asyncio
from datetime import datetime, timedelta


async def demo_delivery_expectation_workflow():
    """
    Complete walkthrough of delivery expectation scenario.
    """
    print("\n" + "="*70)
    print("DEMO: Delivery Expectation with Temporal Context Override")
    print("="*70)
    
    # Simulate database (in real system, use actual echoBell.db)
    conn = sqlite3.connect(":memory:")
    
    # Setup schema
    setup_demo_schema(conn)
    
    # ========================================================================
    # STEP 1: User Says "We're expecting pizza in 2 hours"
    # ========================================================================
    
    print("\n" + "-"*70)
    print("STEP 1: User creates delivery expectation")
    print("-"*70)
    
    print("\nUser: \"Hey Echobell, we're expecting pizza in 2 hours\"")
    print("\nLLM processes voice command...")
    print("LLM calls MCP tool: create_scheduled_event()")
    
    now = int(time.time())
    delivery_window_end = now + 7200  # 2 hours
    
    # Create scheduled event
    conn.execute("""
        INSERT INTO scheduled_event (name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "Pizza Delivery Expected",
        "Expecting pizza delivery from user voice command",
        now,
        delivery_window_end,
        "expecting_delivery",
        now,
        now
    ))
    conn.commit()
    
    event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    print(f"\n✓ Scheduled event created:")
    print(f"  - ID: {event_id}")
    print(f"  - Name: Pizza Delivery Expected")
    print(f"  - Window: {format_timestamp(now)} → {format_timestamp(delivery_window_end)}")
    print(f"  - Duration: 2 hours")
    print(f"  - Policy hint: expecting_delivery")
    
    # ========================================================================
    # STEP 2: 45 Minutes Later - Unknown Vehicle Arrives
    # ========================================================================
    
    print("\n" + "-"*70)
    print("STEP 2: 45 minutes later - Unknown vehicle arrives")
    print("-"*70)
    
    arrival_time = now + 2700  # 45 minutes later
    
    print(f"\nTime: {format_timestamp(arrival_time)} (45 min into delivery window)")
    print("\nCamera detects vehicle...")
    print("  - No plate match in trusted_plates")
    print("  - No uniform visible")
    print("  - Classification: authority (confidence=0.42)")
    print("  - Reason: Low confidence, vehicle-only detection")
    
    # Create visitor event with low confidence classification
    visitor_event_id = "evt_" + str(arrival_time)
    conn.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        visitor_event_id,
        "visitor_unknown_" + str(arrival_time),
        1,
        arrival_time,
        "authority",  # Low confidence classification
        0.42,
        50,
        '{"vision": {"vehicle_present": true}}'
    ))
    conn.commit()
    
    print(f"\n✓ Visitor event created: {visitor_event_id}")
    print(f"  - Intent: authority")
    print(f"  - Confidence: 0.42 (LOW)")
    print(f"  - Urgency: 50")
    
    # ========================================================================
    # STEP 3: Policy Evaluation
    # ========================================================================
    
    print("\n" + "-"*70)
    print("STEP 3: Policy evaluation with temporal context")
    print("-"*70)
    
    print("\nPolicy evaluator checks conditions:")
    print("  ✓ evidence_exists: vehicle_present = TRUE")
    print("  ✓ active_event: expecting_delivery = TRUE")
    print("    - Event 'Pizza Delivery Expected' is active")
    print("    - Current time within window")
    print("  ✓ NOT trusted_plate = TRUE")
    print("")
    print("→ Policy 'expected_delivery_override' MATCHES")
    
    # ========================================================================
    # STEP 4: Reclassify Action Execution
    # ========================================================================
    
    print("\n" + "-"*70)
    print("STEP 4: Execute reclassify action")
    print("-"*70)
    
    print("\nAction: reclassify")
    print("  - event_id: {}")
    print("  - intent: delivery_arriving")
    print("  - confidence: 0.85")
    print("  - reason: Active delivery expectation window")
    
    # Simulate reclassification
    conn.execute("""
        UPDATE visitor_events
        SET intent_inferred = ?,
            intent_confidence = ?,
            reclassified_by = ?,
            reclassification_reason = ?,
            reclassified_ts = ?,
            reclassification_count = COALESCE(reclassification_count, 0) + 1
        WHERE event_id = ?
    """, (
        "delivery_arriving",
        0.85,
        "policy",
        "Active delivery expectation window (scheduled event)",
        arrival_time,
        visitor_event_id
    ))
    conn.commit()
    
    print("\n✓ Reclassification complete:")
    print("  - Original: authority (conf=0.42)")
    print("  - New: delivery_arriving (conf=0.85)")
    print("  - Method: Policy-driven override")
    print("  - Confidence boost: +43%")
    
    # ========================================================================
    # STEP 5: Additional Actions Execute
    # ========================================================================
    
    print("\n" + "-"*70)
    print("STEP 5: Additional policy actions")
    print("-"*70)
    
    print("\nAction: speak")
    print("  → TTS: \"Your delivery has arrived!\"")
    
    print("\nAction: telegram")
    print("  → Notification sent")
    print("  → Priority: low")
    print("  → Message: \"🍕 Delivery arrived at Front Door (expected)\"")
    
    # ========================================================================
    # STEP 6: Query Final State
    # ========================================================================
    
    print("\n" + "-"*70)
    print("STEP 6: Final state verification")
    print("-"*70)
    
    cursor = conn.execute("""
        SELECT event_id, intent_inferred, intent_confidence, 
               reclassified_by, reclassification_reason,
               reclassification_count
        FROM visitor_events
        WHERE event_id = ?
    """, (visitor_event_id,))
    
    row = cursor.fetchone()
    
    print(f"\nEvent: {row[0]}")
    print(f"  Intent: {row[1]}")
    print(f"  Confidence: {row[2]:.2f}")
    print(f"  Reclassified by: {row[3]}")
    print(f"  Reason: {row[4]}")
    print(f"  Reclassification count: {row[5]}")
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    print("\n✅ Temporal context override successful!")
    print("")
    print("Benefits:")
    print("  • Low-confidence 'authority' → High-confidence 'delivery_arriving'")
    print("  • User-friendly announcement instead of alert")
    print("  • Low-priority notification (delivery expected)")
    print("  • Complete audit trail for debugging")
    print("")
    print("Key Components:")
    print("  1. Scheduled Events - Store temporal expectations")
    print("  2. active_event condition - Check if event is active")
    print("  3. Reclassify action - Override intent with context")
    print("  4. Policy priority - High priority overrides normal classification")
    print("")
    print("Policy Layer Advantages:")
    print("  • Central intelligence across all cameras")
    print("  • Temporal context awareness")
    print("  • Easy to customize and test")
    print("  • Full audit trail")
    print("  • Voice/API integration for creating expectations")
    
    conn.close()


def setup_demo_schema(conn: sqlite3.Connection):
    """Create minimal schema for demo."""
    
    # Scheduled events
    conn.execute("""
        CREATE TABLE scheduled_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER NOT NULL,
            policy_hint TEXT,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )
    """)
    
    # Visitor events
    conn.execute("""
        CREATE TABLE visitor_events (
            event_id TEXT PRIMARY KEY,
            visitor_id TEXT,
            camera_id INTEGER,
            detected_ts INTEGER,
            intent_inferred TEXT,
            intent_confidence REAL,
            urgency INTEGER,
            evidence_json TEXT,
            reclassified_by TEXT,
            reclassification_reason TEXT,
            reclassified_ts INTEGER,
            reclassification_count INTEGER DEFAULT 0
        )
    """)
    
    conn.commit()


def format_timestamp(ts: int) -> str:
    """Format unix timestamp as readable string."""
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


# ============================================================================
# Additional Examples
# ============================================================================

async def demo_multiple_expectations():
    """
    Show how to handle multiple overlapping expectations.
    """
    print("\n" + "="*70)
    print("DEMO: Multiple Overlapping Expectations")
    print("="*70)
    
    print("\nScenario:")
    print("  - 10:00 AM: User expects technician at 2 PM")
    print("  - 12:00 PM: User orders pizza for 1 PM delivery")
    print("  - 1:05 PM: Vehicle arrives (unknown plate)")
    print("  - 2:05 PM: Different vehicle arrives (work truck)")
    
    print("\nPolicy Resolution:")
    print("  1:05 PM arrival:")
    print("    - Policy 'expected_delivery_override' matches (pizza window)")
    print("    - Priority: 90")
    print("    - Result: delivery_arriving")
    print("")
    print("  2:05 PM arrival:")
    print("    - Policy 'service_appointment_window' matches (technician window)")
    print("    - Priority: 85")
    print("    - Result: technician_visit")
    
    print("\n✅ Multiple expectations handled correctly!")
    print("   Each arrival matched to appropriate expectation.")


async def demo_voice_integration():
    """
    Show the complete voice command flow.
    """
    print("\n" + "="*70)
    print("DEMO: Voice Command Integration")
    print("="*70)
    
    print("\n1. User voice command:")
    print("   User: \"Hey Echobell, we're expecting pizza in 90 minutes\"")
    
    print("\n2. Echonet processing:")
    print("   → Voiceprint matched: alice (confidence=0.92)")
    print("   → POST /voice/listen")
    
    print("\n3. Policy server processing:")
    print("   → Map voiceprint → trusted_person")
    print("   → Check authorization (conf >= 0.75) ✓")
    print("   → Route to LLM (voice_llm_fallback policy)")
    
    print("\n4. LLM processing:")
    print("   → Parse intent: create delivery expectation")
    print("   → Calculate time window: now + 5400s (90 min)")
    print("   → Call MCP tool: create_scheduled_event()")
    
    print("\n5. MCP tool execution:")
    print("   → Authorized: create_scheduled_event (voice=yes, conf=0.92)")
    print("   → Create scheduled_event record")
    print("   → Policy hint: 'expecting_delivery'")
    
    print("\n6. Response to user:")
    print("   → LLM: \"I've noted that you're expecting pizza in 90 minutes.\"")
    print("   → LLM: \"I'll watch for delivery vehicles and let you know when they arrive.\"")
    print("   → TTS sent to Echonet")
    
    print("\n✅ Complete voice-to-policy integration!")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    print("\n🍕 Delivery Expectation Workflow Demos")
    print("="*70)
    
    # Run main demo
    asyncio.run(demo_delivery_expectation_workflow())
    
    # Run additional demos
    asyncio.run(demo_multiple_expectations())
    asyncio.run(demo_voice_integration())
    
    print("\n" + "="*70)
    print("All demos complete! 🎉")
    print("="*70)
    print("\nNext steps:")
    print("  1. Add reclassify action handler to your system")
    print("  2. Load delivery expectation policy")
    print("  3. Test with: \"Hey Echobell, expecting pizza in 2 hours\"")
    print("  4. Verify unknown vehicles reclassified as delivery")
    print("")
