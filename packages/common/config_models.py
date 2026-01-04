from dataclasses import dataclass


@dataclass
class RetentionSettings:
    """
    Configuration for visitor snapshot retention and saving behavior.
    """
    # Whether or not to save visitor snapshots
    save_visitor_snapshot: bool = True
    
    # Minimum time gap between snapshots for the same visitor (in seconds)
    # Default: 3600 seconds = 1 hour
    gap_between_visits_seconds: int = 3600
    
    # How long to carry forward intent across cameras for the same visitor (in seconds)
    # Used for cross-camera intent persistence (e.g., fire fighter at driveway → door)
    # Default: 3600 seconds = 1 hour
    intent_persistence_window_s: int = 3600
    
    # Grace period for scene tracking (in seconds)
    # How long to wait before marking an object as "exited" when not detected
    # Prevents false exits during brief occlusions or camera handoffs
    # Default: 6 seconds
    scene_tracking_grace_period_s: int = 6

