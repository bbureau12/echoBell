"""
Presence Aggregator

Calculates presence confidence by aggregating multiple signals with time decay.

Algorithm:
1. Collect recent evidence (last hour)
2. Apply time decay based on signal age
3. Combine signals using weighted average
4. Generate human-readable reasons
"""

import math
import time
from typing import List, Dict, Any, Tuple
from .presence_service import PresenceEvent, PresenceState, PresenceStatus, PresenceSignal


# Time decay configurations (in seconds)
TIME_DECAY_CONFIG = {
    "phone": {
        "half_life": 300,  # 5 minutes (high decay - phones are mobile)
        "max_age": 900,    # 15 minutes (after this, confidence near zero)
    },
    "plate": {
        "half_life": 3600,  # 1 hour (low decay - cars stay parked)
        "max_age": 7200,    # 2 hours
    },
    "face": {
        "half_life": 1800,  # 30 minutes (medium decay)
        "max_age": 3600,    # 1 hour
    },
    "manual": {
        "half_life": None,  # No decay until expiration
        "max_age": None,    # Check metadata for expiration
    },
    "bluetooth": {
        "half_life": 180,  # 3 minutes (very high decay - Bluetooth is short range)
        "max_age": 600,    # 10 minutes
    },
    "other": {
        "half_life": 600,  # 10 minutes (default)
        "max_age": 1800,   # 30 minutes
    },
}


def calculate_time_decay(age_seconds: int, source: str) -> float:
    """
    Calculate time decay factor for a signal.
    
    Uses exponential decay: confidence = e^(-age / half_life)
    
    Args:
        age_seconds: How old the signal is
        source: Signal source ("phone", "plate", etc.)
    
    Returns:
        Decay factor between 0.0 and 1.0
    """
    config = TIME_DECAY_CONFIG.get(source, TIME_DECAY_CONFIG["other"])
    
    # Manual overrides don't decay (checked separately for expiration)
    if config["half_life"] is None:
        return 1.0
    
    # If beyond max age, return near-zero
    if config["max_age"] and age_seconds > config["max_age"]:
        return 0.01
    
    # Exponential decay: 0.5 at half_life, approaches 0 as age increases
    decay = math.exp(-age_seconds / config["half_life"])
    
    return max(0.0, min(1.0, decay))


def is_manual_override_expired(event: PresenceEvent, current_time: int) -> bool:
    """
    Check if a manual override has expired.
    
    Args:
        event: The presence event
        current_time: Current timestamp
    
    Returns:
        True if expired
    """
    if event.source.value != "manual":
        return False
    
    if not event.metadata:
        return False
    
    expires_at = event.metadata.get("expires_at")
    if expires_at is None:
        return False  # No expiration
    
    return current_time > expires_at


def combine_signals(signals: List[Tuple[float, str]]) -> Tuple[float, PresenceStatus]:
    """
    Combine multiple signals into a final confidence and status.
    
    Uses weighted average with sign:
    - Positive confidence = home
    - Negative confidence = away
    
    Args:
        signals: List of (confidence, direction) tuples
                 direction is "home" or "away"
    
    Returns:
        (final_confidence, status)
    """
    if not signals:
        return 0.0, PresenceStatus.UNCERTAIN
    
    # Convert to signed values
    signed_values = []
    for confidence, direction in signals:
        if direction == "home":
            signed_values.append(confidence)
        else:  # away
            signed_values.append(-confidence)
    
    # Weighted average (stronger signals dominate)
    # Use squared weights to give more weight to high-confidence signals
    weights = [abs(v) ** 2 for v in signed_values]
    total_weight = sum(weights)
    
    if total_weight == 0:
        return 0.0, PresenceStatus.UNCERTAIN
    
    final_value = sum(v * w for v, w in zip(signed_values, weights)) / total_weight
    
    # Determine status based on threshold
    if final_value > 0.6:
        status = PresenceStatus.HOME
    elif final_value < -0.6:
        status = PresenceStatus.AWAY
    else:
        status = PresenceStatus.UNCERTAIN
    
    # Return absolute confidence
    final_confidence = abs(final_value)
    
    return final_confidence, status


def generate_reasons(events: List[PresenceEvent], current_time: int) -> List[str]:
    """
    Generate human-readable reasons for presence status.
    
    Args:
        events: Recent presence events
        current_time: Current timestamp
    
    Returns:
        List of reason strings
    """
    reasons = []
    
    # Track what we've seen
    phone_seen = None
    vehicles_present = []
    face_seen = None
    manual_override = None
    
    for event in events:
        age_seconds = current_time - event.timestamp
        
        # Skip expired manual overrides
        if is_manual_override_expired(event, current_time):
            continue
        
        # Skip very old signals
        if age_seconds > TIME_DECAY_CONFIG.get(event.source.value, {}).get("max_age", 3600):
            continue
        
        if event.signal == PresenceSignal.HEARTBEAT:
            if phone_seen is None or event.timestamp > phone_seen:
                phone_seen = age_seconds
        
        elif event.signal == PresenceSignal.VEHICLE_PRESENT:
            vehicle_name = event.subject_id.split("_")[-1]  # Extract "tesla" from "beau_tesla"
            if vehicle_name not in vehicles_present:
                vehicles_present.append(vehicle_name)
        
        elif event.signal == PresenceSignal.FACE_SEEN:
            if face_seen is None or event.timestamp > face_seen:
                face_seen = age_seconds
        
        elif event.signal in (PresenceSignal.OVERRIDE_HOME, PresenceSignal.OVERRIDE_AWAY):
            if manual_override is None or event.timestamp > manual_override[0]:
                override_reason = event.metadata.get("reason", "Manual override") if event.metadata else "Manual override"
                manual_override = (event.timestamp, override_reason, event.signal)
    
    # Build reasons in priority order
    if manual_override:
        _, override_reason, signal = manual_override
        reasons.append(f"manual: {override_reason}")
    
    if phone_seen is not None:
        minutes = int(phone_seen / 60)
        if minutes == 0:
            reasons.append("phone_seen_just_now")
        elif minutes == 1:
            reasons.append("phone_seen_1m_ago")
        else:
            reasons.append(f"phone_seen_{minutes}m_ago")
    
    if vehicles_present:
        if len(vehicles_present) == 1:
            reasons.append(f"{vehicles_present[0]}_present")
        else:
            reasons.append(f"{len(vehicles_present)}_vehicles_present")
    
    if face_seen is not None:
        minutes = int(face_seen / 60)
        if minutes < 5:
            reasons.append(f"face_seen_{minutes}m_ago")
    
    return reasons or ["no_recent_evidence"]


def extract_evidence_summary(events: List[PresenceEvent], current_time: int) -> Dict[str, Any]:
    """
    Extract structured evidence summary.
    
    Args:
        events: Recent presence events
        current_time: Current timestamp
    
    Returns:
        Evidence dictionary
    """
    evidence = {
        "phone_last_seen": None,
        "vehicles_present": [],
        "face_last_seen": None,
        "manual_override": None,
    }
    
    for event in events:
        # Skip expired manual overrides
        if is_manual_override_expired(event, current_time):
            continue
        
        if event.signal == PresenceSignal.HEARTBEAT:
            if evidence["phone_last_seen"] is None or event.timestamp > evidence["phone_last_seen"]:
                evidence["phone_last_seen"] = event.timestamp
        
        elif event.signal == PresenceSignal.VEHICLE_PRESENT:
            vehicle_name = event.subject_id.split("_")[-1]
            if vehicle_name not in evidence["vehicles_present"]:
                evidence["vehicles_present"].append(vehicle_name)
        
        elif event.signal == PresenceSignal.FACE_SEEN:
            if evidence["face_last_seen"] is None or event.timestamp > evidence["face_last_seen"]:
                evidence["face_last_seen"] = event.timestamp
        
        elif event.signal in (PresenceSignal.OVERRIDE_HOME, PresenceSignal.OVERRIDE_AWAY):
            if evidence["manual_override"] is None or event.timestamp > evidence["manual_override"]["timestamp"]:
                evidence["manual_override"] = {
                    "timestamp": event.timestamp,
                    "status": "home" if event.signal == PresenceSignal.OVERRIDE_HOME else "away",
                    "reason": event.metadata.get("reason") if event.metadata else None,
                }
    
    return evidence


def calculate_presence_state(events: List[PresenceEvent], current_time: int) -> PresenceState:
    """
    Calculate presence state from recent events.
    
    This is the main aggregation function that combines multiple signals
    with time decay to determine current presence.
    
    Args:
        events: Recent presence events (typically last hour)
        current_time: Current timestamp
    
    Returns:
        PresenceState with status, confidence, and reasons
    """
    if not events:
        # No evidence = uncertain
        return PresenceState(
            person_id=events[0].person_id if events else "unknown",
            status=PresenceStatus.UNCERTAIN,
            confidence=0.0,
            last_updated=current_time,
            reasons=["no_recent_evidence"],
            evidence={},
            raw_signals=[],
        )
    
    person_id = events[0].person_id
    signals = []
    raw_signals = []
    
    for event in events:
        # Skip expired manual overrides
        if is_manual_override_expired(event, current_time):
            continue
        
        # Calculate age and decay
        age_seconds = current_time - event.timestamp
        time_factor = calculate_time_decay(age_seconds, event.source.value)
        
        # Get signal confidence (default to 1.0 for definitive signals)
        signal_conf = event.confidence if event.confidence is not None else 1.0
        
        # Apply time decay
        decayed_conf = signal_conf * time_factor
        
        # Determine direction (home vs away)
        direction = "home" if event.is_home_signal else "away"
        
        # Add to signals
        if decayed_conf > 0.01:  # Ignore very weak signals
            signals.append((decayed_conf, direction))
            raw_signals.append({
                "source": event.source.value,
                "signal": event.signal.value,
                "confidence": signal_conf,
                "time_factor": round(time_factor, 3),
                "decayed_confidence": round(decayed_conf, 3),
                "age_seconds": age_seconds,
                "direction": direction,
            })
    
    # Combine signals
    final_confidence, status = combine_signals(signals)
    
    # Generate human-readable reasons
    reasons = generate_reasons(events, current_time)
    
    # Extract evidence summary
    evidence = extract_evidence_summary(events, current_time)
    
    return PresenceState(
        person_id=person_id,
        status=status,
        confidence=round(final_confidence, 3),
        last_updated=current_time,
        reasons=reasons,
        evidence=evidence,
        raw_signals=raw_signals,
    )
