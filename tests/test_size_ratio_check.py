"""
Test size ratio checks for person-vehicle linkage.

Ensures that:
- Bicycles: Person can be larger than vehicle
- Cars/trucks: Person must be smaller than vehicle
- Filters out: head clips, toy vehicles, misdetections
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.scene.scene_linkage import _size_ratio_check


class TestSizeRatioCheck:
    """Test vehicle-type-aware size ratio validation."""
    
    def test_bicycle_person_larger_accepted(self):
        """Person larger than bicycle should be accepted."""
        # Person: 150px tall
        person_box = (100, 100, 200, 250)
        # Bicycle: 80px tall (smaller than person)
        bicycle_box = (220, 140, 300, 220)
        
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is True
    
    def test_bicycle_person_smaller_accepted(self):
        """Person smaller than bicycle (but not tiny) should be accepted."""
        # Person: 100px tall (child)
        person_box = (100, 150, 180, 250)
        # Bicycle: 110px tall
        bicycle_box = (220, 130, 310, 240)
        
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is True
    
    def test_bicycle_person_tiny_clip_rejected(self):
        """Tiny person clip (head brushing corner) should be rejected."""
        # Person: 30px tall (just head)
        person_box = (100, 200, 120, 230)
        # Bicycle: 100px tall
        bicycle_box = (220, 140, 320, 240)
        
        # Ratio = 30/100 = 0.3, below 0.8 threshold
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is False
    
    def test_bicycle_absurdly_large_person_rejected(self):
        """Person 3x larger than bike (probably toy bike) rejected."""
        # Person: 200px tall
        person_box = (100, 50, 250, 250)
        # Tiny bike: 60px tall (toy?)
        bicycle_box = (280, 180, 330, 240)
        
        # Ratio = 200/60 = 3.33, above 2.5 threshold
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is False
    
    def test_car_normal_ratio_accepted(self):
        """Person appropriately smaller than car should be accepted."""
        # Person: 150px tall
        person_box = (100, 100, 200, 250)
        # Car: 300px tall
        car_box = (350, 80, 650, 380)
        
        # Ratio = 150/300 = 0.5, within 0.15 to 0.85 range
        assert _size_ratio_check(person_box, car_box, "car") is True
    
    def test_car_person_too_small_rejected(self):
        """Tiny person clip (head corner) relative to car rejected."""
        # Person: 30px tall (just head)
        person_box = (100, 200, 120, 230)
        # Car: 300px tall
        car_box = (150, 80, 450, 380)
        
        # Ratio = 30/300 = 0.1, below 0.15 threshold
        assert _size_ratio_check(person_box, car_box, "car") is False
    
    def test_car_person_too_large_rejected(self):
        """Person nearly as big as car (misdetection) rejected."""
        # Person: 180x280 = diag 334
        person_box = (100, 100, 280, 380)
        # Car: 200x200 = diag 283 (person actually bigger!)
        car_box = (300, 150, 500, 350)
        
        # Ratio = 334/283 = 1.18, above 0.85 threshold
        assert _size_ratio_check(person_box, car_box, "car") is False
    
    def test_truck_normal_ratio_accepted(self):
        """Person much smaller than truck should be accepted."""
        # Person: 120px tall
        person_box = (100, 200, 180, 320)
        # Truck: 500px tall
        truck_box = (350, 50, 900, 550)
        
        # Ratio = 120/500 = 0.24, within 0.15 to 0.85 range
        assert _size_ratio_check(person_box, truck_box, "truck") is True
    
    def test_motorcycle_person_larger_accepted(self):
        """Person on motorcycle can be larger."""
        # Person: 160px tall
        person_box = (100, 80, 220, 240)
        # Motorcycle: 90px tall
        motorcycle_box = (250, 140, 350, 230)
        
        assert _size_ratio_check(person_box, motorcycle_box, "motorbike") is True
    
    def test_unknown_vehicle_uses_car_thresholds(self):
        """Unknown vehicle type defaults to car thresholds."""
        # Person: 150px tall
        person_box = (100, 100, 200, 250)
        # Unknown vehicle: 300px tall
        vehicle_box = (350, 80, 650, 380)
        
        # Should use car thresholds (0.15 to 0.85)
        assert _size_ratio_check(person_box, vehicle_box, None) is True
        assert _size_ratio_check(person_box, vehicle_box, "unknown") is True
    
    def test_suspiciously_small_vehicle_rejected(self):
        """Vehicles with diagonal < 5px are rejected."""
        # Person: 100px tall
        person_box = (100, 100, 150, 200)
        # Tiny vehicle: 3px (probably noise)
        tiny_vehicle_box = (200, 200, 202, 203)
        
        assert _size_ratio_check(person_box, tiny_vehicle_box, "car") is False


class TestSizeRatioEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_bicycle_at_lower_threshold(self):
        """Test person at 0.8x bicycle size (boundary)."""
        # Person: 80px, Bicycle: 100px → ratio = 0.8
        person_box = (0, 0, 50, 80)
        bicycle_box = (100, 0, 160, 100)
        
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is True
    
    def test_bicycle_just_below_lower_threshold(self):
        """Test person at 0.79x bicycle size (just below boundary)."""
        # Person: 40x60 = diag 72
        # Bicycle: 60x100 = diag 117
        # Ratio = 72/117 = 0.615, below 0.8
        person_box = (0, 0, 40, 60)
        bicycle_box = (100, 0, 160, 100)
        
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is False
    
    def test_car_at_upper_threshold(self):
        """Test person at 0.85x car size (boundary)."""
        # Person: 170px, Car: 200px → ratio = 0.85
        person_box = (0, 0, 100, 170)
        car_box = (150, 0, 300, 200)
        
        assert _size_ratio_check(person_box, car_box, "car") is True
    
    def test_car_just_above_upper_threshold(self):
        """Test person at 0.86x car size (just above boundary)."""
        # Person: 120x160 = diag 200
        # Car: 150x180 = diag 234
        # Ratio = 200/234 = 0.855, just above 0.85
        person_box = (0, 0, 120, 160)
        car_box = (150, 0, 300, 180)
        
        assert _size_ratio_check(person_box, car_box, "car") is False
    
    def test_wide_person_tall_bicycle(self):
        """Test diagonal calculation with different aspect ratios."""
        # Person: wide (100x80) → diag = 128
        person_box = (0, 0, 100, 80)
        # Bicycle: tall (60x100) → diag = 117
        bicycle_box = (150, 0, 210, 100)
        
        # Ratio = 128/117 = 1.09, within bicycle range
        assert _size_ratio_check(person_box, bicycle_box, "bicycle") is True
