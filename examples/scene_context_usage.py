# Example: Using scene context in policies

"""
Scenario: AC Technician present for 40 minutes, then Fire Department arrives

With the new scene_context module, policies can detect this:
"""

import sqlite3
from packages.scene.scene_context import (
    get_active_scene_intents,
    get_scene_urgency_level,
    check_concurrent_intents,
)


def evaluate_scene_based_policy(conn: sqlite3.Connection, camera_id: int, now_ts: int):
    """
    Example policy evaluation that considers the ENTIRE current scene,
    not just the most recent event.
    """
    
    # Get all active intents in the scene
    active_intents = get_active_scene_intents(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
    )
    
    print(f"\n=== Scene Analysis (Camera {camera_id}) ===")
    print(f"Active entities: {len(active_intents)}")
    
    for ai in active_intents:
        print(f"  - {ai.track_type}: {ai.intent} (urgency={ai.urgency}, conf={ai.confidence:.2f})")
    
    # Get overall scene urgency
    max_urgency, description, intent_names = get_scene_urgency_level(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
    )
    
    print(f"\nScene Status: {description}")
    print(f"Max Urgency: {max_urgency}")
    
    # Policy Rules:
    
    # Rule 1: Authority + anyone else = immediate escalation
    if check_concurrent_intents(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        required_intents=["authority_urgent", "technician_visit"],
    ):
        return {
            "action": "ESCALATE_IMMEDIATELY",
            "reason": "Fire department arrived while technician on site",
            "notify": ["homeowner", "emergency_contact"],
            "urgency": 95,
        }
    
    # Rule 2: Multiple service providers = notify homeowner
    service_intents = [ai for ai in active_intents if ai.intent in ["technician_visit", "delivery", "maintenance"]]
    if len(service_intents) > 1:
        return {
            "action": "NOTIFY",
            "reason": f"Multiple service providers on site: {[ai.intent for ai in service_intents]}",
            "notify": ["homeowner"],
            "urgency": 40,
        }
    
    # Rule 3: High urgency = use scene description
    if max_urgency >= 90:
        return {
            "action": "ALERT",
            "reason": description,
            "notify": ["homeowner", "emergency_contact"],
            "urgency": max_urgency,
        }
    
    # Rule 4: Normal single visitor
    return {
        "action": "LOG",
        "reason": f"Normal scene: {intent_names[0] if intent_names else 'unknown'}",
        "notify": [],
        "urgency": max_urgency,
    }


# Example: Your specific scenario

def demo_scenario():
    """
    Demonstrates the AC technician + fire department scenario.
    """
    import time
    
    conn = sqlite3.connect(":memory:")  # Example only
    
    # Simulate the scenario timeline:
    base_ts = int(time.time())
    
    print("\n" + "="*60)
    print("SCENARIO: AC Technician + Fire Department")
    print("="*60)
    
    # Time 0:00 - Technician arrives
    print("\n[T+0:00] AC Technician arrives")
    print("  Event created: intent='technician_visit', urgency=30")
    print("  Scene tracking: vehicle tracked by plate_hmac")
    
    # Time 0:40 - Fire department arrives
    print("\n[T+0:40] Fire Department arrives")
    print("  Event created: intent='authority_urgent', urgency=90")
    print("  Scene tracking: second vehicle tracked")
    
    print("\n[T+0:40] Policy evaluation using scene_context:")
    
    # THIS is where the magic happens:
    # Even though we have TWO separate events, scene_context sees BOTH
    
    print("""
    >>> active_intents = get_active_scene_intents(conn, camera_id=1, now_ts=now)
    >>> print(active_intents)
    [
        ActiveIntent(intent='authority_urgent', urgency=90, track_type='vehicle'),
        ActiveIntent(intent='technician_visit', urgency=30, track_type='vehicle')
    ]
    
    >>> policy = evaluate_scene_based_policy(conn, camera_id=1, now_ts=now)
    >>> print(policy)
    {
        'action': 'ESCALATE_IMMEDIATELY',
        'reason': 'Fire department arrived while technician on site',
        'notify': ['homeowner', 'emergency_contact'],
        'urgency': 95
    }
    """)
    
    print("\n" + "="*60)
    print("KEY INSIGHT:")
    print("="*60)
    print("""
- Each arrival gets its OWN event (clean, simple)
- Scene tracking maintains WHO'S PRESENT (via scene_tracks)
- Policies query scene_context to see CONCURRENT intents
- Rules can trigger on combinations: "authority + technician"
- No complex intent merging or event updating needed
    """)


if __name__ == "__main__":
    demo_scenario()
