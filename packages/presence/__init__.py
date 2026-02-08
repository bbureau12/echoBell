"""
Presence Tracking Package

Tracks who is currently home based on multiple evidence sources.
"""

from .presence_service import (
    PresenceService,
    PresenceEvent,
    PresenceState,
    PresenceStatus,
    PresenceSource,
    PresenceSignal,
    create_presence_service,
)

from .aggregator import (
    calculate_presence_state,
    calculate_time_decay,
)

__all__ = [
    # Service
    "PresenceService",
    "create_presence_service",
    
    # Data classes
    "PresenceEvent",
    "PresenceState",
    
    # Enums
    "PresenceStatus",
    "PresenceSource",
    "PresenceSignal",
    
    # Aggregation
    "calculate_presence_state",
    "calculate_time_decay",
]
