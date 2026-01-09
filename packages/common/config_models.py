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


@dataclass
class LinkageSettings:
    """
    Configuration for scene linkage (person-vehicle, package-person relationships).
    All thresholds are tunable to balance precision vs recall.
    """
    # Person-to-Vehicle Linkage Settings
    # ==================================
    
    # Time window for "first appearance" linkage (in seconds)
    # Only link people to vehicles if person appeared within this window
    # Default: 3 seconds (person just got out of vehicle)
    person_vehicle_first_appearance_window_s: int = 3
    
    # Maximum age for person to be eligible for vehicle linkage (in seconds)
    # Prevents linking people who have been on scene too long
    # Default: 3600 seconds = 1 hour
    person_vehicle_max_person_age_s: int = 3600
    
    # Maximum age for vehicle to be eligible for linkage (in seconds)
    # Prevents linking people to vehicles that have been parked for hours
    # Default: 3600 seconds = 1 hour
    person_vehicle_max_vehicle_age_s: int = 3600
    
    # Maximum normalized distance between person and vehicle
    # Distance is normalized by vehicle size (distance / max(width, height))
    # Default: 1.2 (person can be 1.2x vehicle size away)
    person_vehicle_max_norm_distance: float = 1.2
    
    # Distance falloff parameter for confidence calculation
    # Higher values = steeper falloff (more penalty for distance)
    # Default: 1.25
    person_vehicle_falloff_k: float = 1.25
    
    # Minimum confidence threshold for creating person-vehicle link
    # Confidence combines proximity + detection confidences
    # Default: 0.15 (lowered to handle edge cases with low YOLO confidence)
    person_vehicle_min_confidence: float = 0.15
    
    # Package-to-Person Linkage Settings
    # ===================================
    
    # Time window for "first appearance" linkage (in seconds)
    # Only link packages to people if package appeared within this window
    # Default: 3 seconds
    package_person_first_appearance_window_s: int = 3
    
    # Minimum containment ratio (package bbox inside person bbox)
    # 0.0 = any overlap, 1.0 = package fully inside person
    # Default: 0.5 (at least 50% of package inside person bbox)
    package_person_min_containment: float = 0.5
    
    # Maximum size ratio (package area / person area)
    # Prevents linking huge "packages" to people
    # Default: 0.8 (package can't be bigger than 80% of person)
    package_person_max_size_ratio: float = 0.8
    
    # Minimum confidence threshold for creating package-person link
    # Default: 0.5
    package_person_min_confidence: float = 0.5
    
    # Package Pickup Detection Settings
    # ==================================
    
    # Maximum time to look back for stationary packages (in seconds)
    # When person appears, check if nearby package disappeared recently
    # Default: 10 seconds
    package_pickup_lookback_window_s: int = 10
    
    # Minimum time package must have been stationary before pickup (in seconds)
    # Ensures we're detecting actual pickups, not packages being carried past
    # Default: 5 seconds
    package_pickup_min_stationary_duration_s: int = 5
    
    # Maximum normalized distance between person and package last position
    # Default: 1.5 (person can be 1.5x package size away from where it was)
    package_pickup_max_norm_distance: float = 1.5
    
    # Minimum confidence threshold for package pickup detection
    # Default: 0.6
    package_pickup_min_confidence: float = 0.6


