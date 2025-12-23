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
