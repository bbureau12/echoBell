#!/usr/bin/env python3
"""
Presence Tracking Demo Scripts

Interactive demonstrations showing how to use the presence tracking system.
Each demo function is self-contained and can be run independently.

Demos:
1. demo_vehicle_presence_hook() - Vehicle detection integration
2. demo_phone_heartbeat() - Phone WiFi heartbeat tracking
3. demo_manual_override_voice() - Voice command overrides
4. demo_policy_condition() - Policy-based decisions
5. demo_multi_person_presence() - Multi-person tracking
6. demo_complete_workflow() - Full day simulation

Run this file to see all demos: python examples/presence_demos.py
"""

import sqlite3
import time
from packages.presence import (
    PresenceService,
    PresenceStatus,
)


def setup_demo_db():
    """Create in-memory database for demo."""
    db = sqlite3.connect(":memory:")
    
    # Create presence tables
    db.execute("""
        CREATE TABLE presence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            source TEXT NOT NULL,
            signal TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            person_id TEXT,
            confidence REAL,
            metadata_json TEXT
        )
    """)
    
    db.execute("""
        CREATE TABLE presence_state (
            person_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            last_updated INTEGER NOT NULL,
            state_json TEXT
        )
    """)
    
    db.commit()
    return db


def demo_vehicle_presence_hook():
    """
    Demo: Hook into vehicle detection to track presence.
    
    When a trusted vehicle is detected, insert presence event.
    """
    print("\n" + "="*70)
    print("DEMO: Vehicle Detection → Presence Tracking")
    print("="*70)
    
    db = setup_demo_db()
    service = PresenceService(db)
    
    # Simulate: Beau's Tesla detected at driveway camera
    print("\n1. Tesla (plate ABC123) detected at driveway")
    service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.92,
        metadata={
            "plate": "ABC123",
            "camera_id": 1,
            "camera_name": "Driveway",
            "event_id": "evt_tesla_123",
        }
    )
    
    # Update presence state
    state = service.update_presence_state("beau")
    print(f"\n   Status: {state.status.value}")
    print(f"   Confidence: {state.confidence:.2f}")
    print(f"   Reasons: {', '.join(state.reasons)}")
    
    # Simulate: 10 minutes later, second vehicle arrives
    print("\n2. Truck (plate XYZ789) detected 10 minutes later")
    service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_truck",
        person_id="beau",
        confidence=0.88,
        timestamp=int(time.time()) + 600,  # 10 min later
        metadata={
            "plate": "XYZ789",
            "camera_id": 2,
            "camera_name": "Garage",
        }
    )
    
    state = service.update_presence_state("beau")
    print(f"\n   Status: {state.status.value}")
    print(f"   Confidence: {state.confidence:.2f}")
    print(f"   Reasons: {', '.join(state.reasons)}")
    print(f"   Vehicles: {state.evidence['vehicles_present']}")


def demo_phone_heartbeat():
    """
    Demo: Phone app sending heartbeats.
    
    Phone app on home WiFi sends heartbeat every 60 seconds.
    """
    print("\n" + "="*70)
    print("DEMO: Phone Heartbeat Integration")
    print("="*70)
    
    db = setup_demo_db()
    service = PresenceService(db)
    
    now = int(time.time())
    
    # Simulate: Phone heartbeats over time
    print("\n1. Phone heartbeat received (WiFi connected)")
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 120,  # 2 minutes ago
        metadata={
            "ip": "192.168.1.50",
            "rssi": -42,
            "connection": "wifi",
            "device": "iPhone 15 Pro",
        }
    )
    
    state = service.update_presence_state("beau")
    print(f"\n   Status: {state.status.value}")
    print(f"   Confidence: {state.confidence:.2f}")
    print(f"   Phone last seen: {now - state.evidence['phone_last_seen']} seconds ago")
    
    # Simulate: Phone hasn't sent heartbeat in 10 minutes
    print("\n2. Phone heartbeat stopped (left WiFi range)")
    print("   Last heartbeat: 10 minutes ago")
    
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 600,  # 10 min ago
        metadata={"ip": "192.168.1.50"}
    )
    
    state = service.update_presence_state("beau")
    print(f"\n   Status: {state.status.value}")
    print(f"   Confidence: {state.confidence:.2f} (decayed due to age)")
    print(f"   Reasons: {', '.join(state.reasons)}")


def demo_manual_override_voice():
    """
    Demo: User tells system they're leaving via voice command.
    
    User: "Hey Echobell, I'm leaving for 2 hours"
    LLM calls presence API to set manual override.
    """
    print("\n" + "="*70)
    print("DEMO: Manual Override via Voice Command")
    print("="*70)
    
    db = setup_demo_db()
    service = PresenceService(db)
    
    now = int(time.time())
    
    # Initial state: Phone + car = home
    print("\n1. Initial state: Phone and car present")
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        timestamp=now - 60
    )
    service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        timestamp=now - 300
    )
    
    state = service.update_presence_state("beau")
    print(f"   Status: {state.status.value}")
    print(f"   Confidence: {state.confidence:.2f}")
    
    # User voice command
    print("\n2. Voice command: 'I'm leaving for 2 hours'")
    service.set_manual_override(
        person_id="beau",
        status="away",
        duration_hours=2,
        reason="Going to store"
    )
    
    state = service.get_presence("beau")
    print(f"   Status: {state.status.value}")
    print(f"   Confidence: {state.confidence:.2f}")
    print(f"   Reasons: {', '.join(state.reasons)}")
    
    print("\n3. Manual override trumps sensor data")
    print("   Even though phone and car are still present,")
    print("   system respects user's explicit statement.")


def demo_policy_condition():
    """
    Demo: Policy uses presence to make decisions.
    
    Policy: "Don't ring doorbell if owner is home"
    """
    print("\n" + "="*70)
    print("DEMO: Policy Integration - Presence-Based Rules")
    print("="*70)
    
    db = setup_demo_db()
    service = PresenceService(db)
    
    now = int(time.time())
    
    # Scenario 1: Owner is home
    print("\n1. Scenario: Owner is home (high confidence)")
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        timestamp=now - 60
    )
    service.update_presence_state("beau")
    
    is_home = service.get_presence("beau").status == PresenceStatus.HOME
    print(f"   Beau is home: {is_home}")
    print(f"   Policy decision: Don't ring doorbell ✓")
    
    # Scenario 2: Owner is away
    print("\n2. Scenario: Owner is away")
    service.set_manual_override(
        person_id="beau",
        status="away",
        duration_hours=1
    )
    
    is_home = service.get_presence("beau").status == PresenceStatus.HOME
    print(f"   Beau is home: {is_home}")
    print(f"   Policy decision: Ring doorbell for visitors ✓")
    
    # Scenario 3: Nobody home
    print("\n3. Scenario: Check if anyone is home")
    anyone_home = service.is_anyone_home()
    print(f"   Anyone home: {anyone_home}")
    print(f"   Policy decision: Enable security alerts ✓")


def demo_multi_person_presence():
    """
    Demo: Track presence for multiple people.
    
    Family with multiple people and vehicles.
    """
    print("\n" + "="*70)
    print("DEMO: Multi-Person Presence Tracking")
    print("="*70)
    
    db = setup_demo_db()
    service = PresenceService(db)
    
    now = int(time.time())
    
    # Person 1: Beau - home (phone + car)
    print("\n1. Beau: Phone heartbeat + Tesla present")
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        timestamp=now - 60
    )
    service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        timestamp=now - 300
    )
    service.update_presence_state("beau")
    
    # Person 2: Sarah - away (phone last seen 30 min ago)
    print("\n2. Sarah: Phone last seen 30 minutes ago")
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="sarah_phone",
        person_id="sarah",
        timestamp=now - 1800
    )
    service.update_presence_state("sarah")
    
    # Get all presence
    print("\n3. Current presence summary:")
    all_states = service.get_all_presence()
    for state in all_states:
        print(f"\n   {state.person_id}:")
        print(f"     Status: {state.status.value}")
        print(f"     Confidence: {state.confidence:.2f}")
        print(f"     Reasons: {', '.join(state.reasons)}")
    
    # Check if anyone home
    anyone = service.is_anyone_home()
    everyone_away = service.is_everyone_away()
    print(f"\n   Anyone home: {anyone}")
    print(f"   Everyone away: {everyone_away}")


def demo_complete_workflow():
    """
    Demo: Complete workflow from vehicle detection to policy action.
    """
    print("\n" + "="*70)
    print("DEMO: Complete Workflow")
    print("="*70)
    
    db = setup_demo_db()
    service = PresenceService(db)
    
    now = int(time.time())
    
    print("\n📱 Morning: Beau's phone connects to WiFi")
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        timestamp=now - 7200,  # 2 hours ago
    )
    service.update_presence_state("beau")
    print(f"   → Status: {service.get_presence('beau').status.value}")
    
    print("\n🚗 9 AM: Beau's car leaves (detected by camera)")
    service.insert_event(
        source="plate",
        signal="vehicle_left",
        subject_id="beau_tesla",
        person_id="beau",
        timestamp=now - 3600,  # 1 hour ago
    )
    service.update_presence_state("beau")
    print(f"   → Status: {service.get_presence('beau').status.value}")
    
    print("\n🗣️  9:30 AM: Voice command - 'I'll be back in 2 hours'")
    service.set_manual_override(
        person_id="beau",
        status="away",
        duration_hours=2,
        reason="Running errands"
    )
    print(f"   → Status: {service.get_presence('beau').status.value}")
    
    print("\n🚪 10 AM: Delivery arrives (nobody home)")
    state = service.get_presence("beau")
    if state.status == PresenceStatus.AWAY:
        print("   → Policy: Send Telegram notification (owner away) ✓")
        print("   → Policy: Don't ring doorbell (nobody home) ✓")
    
    print("\n🚗 11 AM: Beau returns (car detected)")
    service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        timestamp=now - 60,
    )
    service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        timestamp=now - 60,
    )
    service.update_presence_state("beau")
    state = service.get_presence("beau")
    print(f"   → Status: {state.status.value}")
    print(f"   → Confidence: {state.confidence:.2f}")
    print(f"   → Reasons: {', '.join(state.reasons)}")


if __name__ == "__main__":
    demo_vehicle_presence_hook()
    demo_phone_heartbeat()
    demo_manual_override_voice()
    demo_policy_condition()
    demo_multi_person_presence()
    demo_complete_workflow()
    
    print("\n" + "="*70)
    print("All demos completed!")
    print("="*70)
