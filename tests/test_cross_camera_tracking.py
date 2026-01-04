"""
Test cross-camera person tracking without photos.

Tests the scene_tracker's ability to track people across multiple cameras,
detect camera handoffs, and determine global person presence in the scene.

All tests use synthetic tracking data (visitor_ids, timestamps, camera_ids)
rather than real images.
"""

import pytest
import sqlite3
import tempfile
import time
from pathlib import Path

from packages.scene.scene_tracker import SceneTracker, Observation


@pytest.fixture
def scene_tracker():
    """Create a scene tracker with standard settings."""
    return SceneTracker(
        iou_match_threshold=0.30,
        grace_period_s=6,
    )


@pytest.fixture
def test_db(scene_tracker):
    """Create a temporary database with scene_tracker schema."""
    db_path = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path.close()
    
    conn = sqlite3.connect(db_path.name)
    scene_tracker.ensure_schema(conn)
    
    yield conn
    
    conn.close()
    Path(db_path.name).unlink()


class TestSingleCameraPersonTracking:
    """Test basic person tracking on a single camera."""
    
    def test_person_appears_on_camera(self, scene_tracker, test_db):
        """Test detecting person on one camera."""
        now = int(time.time())
        
        # Person appears on camera 1
        observations = [
            Observation(
                track_type="person",
                box=(100, 100, 200, 300),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=observations,
        )
        
        # Check person is active on camera 1
        tracks = scene_tracker.get_currently_present(
            test_db,
            camera_id=1,
            track_type="person",
            now_ts=now,
        )
        
        assert len(tracks) == 1
        assert tracks[0].track_key == "visitor_001"
        assert tracks[0].camera_id == 1
    
    def test_person_exits_single_camera(self, scene_tracker, test_db):
        """Test person exiting after grace period."""
        now = int(time.time())
        
        # Person appears
        observations = [
            Observation(
                track_type="person",
                box=(100, 100, 200, 300),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=observations,
        )
        
        # Wait beyond grace period with no observations
        later = now + 10  # 10 seconds > 6 second grace period
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=later,
            observations=[],
        )
        
        # Person should be marked as exited
        tracks = scene_tracker.get_currently_present(
            test_db,
            camera_id=1,
            track_type="person",
            now_ts=later,
        )
        
        assert len(tracks) == 0


class TestCrossCameraPersonTracking:
    """Test person tracking across multiple cameras."""
    
    def test_person_active_on_one_camera(self, scene_tracker, test_db):
        """Test is_person_active_anywhere with person on one camera."""
        now = int(time.time())
        
        # Person appears on camera 1
        observations = [
            Observation(
                track_type="person",
                box=(100, 100, 200, 300),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=observations,
        )
        
        # Check person is active anywhere
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=now,
        )
        
        assert is_active is True
    
    def test_person_active_on_multiple_cameras(self, scene_tracker, test_db):
        """Test person visible on multiple cameras simultaneously."""
        now = int(time.time())
        
        # Person appears on camera 1
        obs_cam1 = [
            Observation(
                track_type="person",
                box=(100, 100, 200, 300),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=obs_cam1,
        )
        
        # Same person appears on camera 2
        obs_cam2 = [
            Observation(
                track_type="person",
                box=(150, 150, 250, 350),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=now,
            observations=obs_cam2,
        )
        
        # Check person is active
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=now,
        )
        
        assert is_active is True
        
        # Check which cameras see the person
        cameras = scene_tracker.get_person_cameras(
            test_db,
            visitor_id="visitor_001",
            now_ts=now,
        )
        
        assert len(cameras) == 2
        assert 1 in cameras
        assert 2 in cameras
    
    def test_camera_handoff(self, scene_tracker, test_db):
        """Test person moving from one camera to another."""
        now = int(time.time())
        
        # T=0: Person appears on camera 1
        obs_cam1 = [
            Observation(
                track_type="person",
                box=(100, 100, 200, 300),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=obs_cam1,
        )
        
        # T=2s: Person disappears from camera 1, appears on camera 2
        handoff_time = now + 2
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=handoff_time,
            observations=[],  # No longer on camera 1
        )
        
        obs_cam2 = [
            Observation(
                track_type="person",
                box=(150, 150, 250, 350),
                visitor_id="visitor_001",
            )
        ]
        
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=handoff_time,
            observations=obs_cam2,
        )
        
        # Person should still be active (on camera 2)
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=handoff_time,
        )
        
        assert is_active is True
        
        # Should only be on camera 2 now (camera 1 within grace period)
        cameras = scene_tracker.get_person_cameras(
            test_db,
            visitor_id="visitor_001",
            now_ts=handoff_time,
        )
        
        # Camera 1 still in grace period, so might be in list
        assert 2 in cameras
    
    def test_person_not_active_anywhere(self, scene_tracker, test_db):
        """Test person not active on any camera."""
        now = int(time.time())
        
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_999",
            now_ts=now,
        )
        
        assert is_active is False
    
    def test_person_exited_all_cameras(self, scene_tracker, test_db):
        """Test person exited from all cameras."""
        now = int(time.time())
        
        # Person appears on cameras 1 and 2
        for camera_id in [1, 2]:
            obs = [
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ]
            
            scene_tracker.update(
                test_db,
                camera_id=camera_id,
                now_ts=now,
                observations=obs,
            )
        
        # Wait beyond grace period on all cameras
        later = now + 10
        
        for camera_id in [1, 2]:
            scene_tracker.update(
                test_db,
                camera_id=camera_id,
                now_ts=later,
                observations=[],
            )
        
        # Person should not be active anywhere
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=later,
        )
        
        assert is_active is False
        
        cameras = scene_tracker.get_person_cameras(
            test_db,
            visitor_id="visitor_001",
            now_ts=later,
        )
        
        assert len(cameras) == 0


class TestMultipleVisitorsMultipleCameras:
    """Test tracking multiple people across multiple cameras."""
    
    def test_multiple_visitors_on_different_cameras(self, scene_tracker, test_db):
        """Test different people on different cameras."""
        now = int(time.time())
        
        # Visitor 001 on camera 1
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Visitor 002 on camera 2
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(150, 150, 250, 350),
                    visitor_id="visitor_002",
                )
            ],
        )
        
        # Check both are active
        assert scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=now,
        ) is True
        
        assert scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_002",
            now_ts=now,
        ) is True
        
        # Get all active visitors
        all_visitors = scene_tracker.get_active_visitors_all_cameras(
            test_db,
            now_ts=now,
        )
        
        assert len(all_visitors) == 2
        assert all_visitors["visitor_001"] == [1]
        assert all_visitors["visitor_002"] == [2]
    
    def test_multiple_visitors_on_same_camera(self, scene_tracker, test_db):
        """Test multiple people on same camera."""
        now = int(time.time())
        
        # Two visitors on camera 1
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                ),
                Observation(
                    track_type="person",
                    box=(300, 100, 400, 300),
                    visitor_id="visitor_002",
                ),
            ],
        )
        
        all_visitors = scene_tracker.get_active_visitors_all_cameras(
            test_db,
            now_ts=now,
        )
        
        assert len(all_visitors) == 2
        assert all_visitors["visitor_001"] == [1]
        assert all_visitors["visitor_002"] == [1]
    
    def test_visitor_on_multiple_cameras_simultaneously(self, scene_tracker, test_db):
        """Test one person visible on multiple cameras at once."""
        now = int(time.time())
        
        # Same visitor on cameras 1, 2, and 3
        for camera_id in [1, 2, 3]:
            scene_tracker.update(
                test_db,
                camera_id=camera_id,
                now_ts=now,
                observations=[
                    Observation(
                        track_type="person",
                        box=(100, 100, 200, 300),
                        visitor_id="visitor_001",
                    )
                ],
            )
        
        all_visitors = scene_tracker.get_active_visitors_all_cameras(
            test_db,
            now_ts=now,
        )
        
        assert len(all_visitors) == 1
        assert sorted(all_visitors["visitor_001"]) == [1, 2, 3]


class TestGracePeriodAcrossCameras:
    """Test grace period behavior with camera handoffs."""
    
    def test_grace_period_maintains_presence_during_handoff(self, scene_tracker, test_db):
        """Test person remains active during camera handoff within grace period."""
        now = int(time.time())
        
        # T=0: Person on camera 1
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # T=3s: Person disappears from camera 1
        handoff_start = now + 3
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=handoff_start,
            observations=[],
        )
        
        # Person still active (within grace period)
        assert scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=handoff_start,
        ) is True
        
        # T=5s: Person appears on camera 2 (before grace period expires)
        handoff_end = now + 5
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=handoff_end,
            observations=[
                Observation(
                    track_type="person",
                    box=(150, 150, 250, 350),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person should be active on camera 2
        cameras = scene_tracker.get_person_cameras(
            test_db,
            visitor_id="visitor_001",
            now_ts=handoff_end,
        )
        
        assert 2 in cameras
    
    def test_exit_then_reenter_creates_new_track(self, scene_tracker, test_db):
        """Test person fully exits then returns."""
        now = int(time.time())
        
        # Person appears on camera 1
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person exits all cameras (wait beyond grace period)
        exit_time = now + 10
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=exit_time,
            observations=[],
        )
        
        # Verify exited
        assert scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=exit_time,
        ) is False
        
        # Person returns on camera 2
        return_time = exit_time + 5
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=return_time,
            observations=[
                Observation(
                    track_type="person",
                    box=(150, 150, 250, 350),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person should be active again
        assert scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=return_time,
        ) is True


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_visitor_id(self, scene_tracker, test_db):
        """Test querying with empty visitor_id."""
        now = int(time.time())
        
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="",
            now_ts=now,
        )
        
        assert is_active is False
    
    def test_no_active_visitors(self, scene_tracker, test_db):
        """Test get_active_visitors_all_cameras with no visitors."""
        now = int(time.time())
        
        all_visitors = scene_tracker.get_active_visitors_all_cameras(
            test_db,
            now_ts=now,
        )
        
        assert len(all_visitors) == 0
        assert all_visitors == {}
    
    def test_visitor_id_with_special_characters(self, scene_tracker, test_db):
        """Test visitor_id with special characters."""
        now = int(time.time())
        special_id = "visitor-001_test@2026"
        
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id=special_id,
                )
            ],
        )
        
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id=special_id,
            now_ts=now,
        )
        
        assert is_active is True
    
    def test_default_timestamp(self, scene_tracker, test_db):
        """Test methods with default timestamp (None)."""
        now = int(time.time())
        
        # Add a recent visitor
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=now,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Check without providing now_ts (should use current time)
        is_active = scene_tracker.is_person_active_anywhere(
            test_db,
            visitor_id="visitor_001",
            now_ts=None,  # Will default to time.time()
        )
        
        # Should be active since we just added them
        assert is_active is True


class TestVisitorPresenceDuration:
    """Test continuous presence duration tracking across cameras."""
    
    def test_single_camera_presence_duration(self, scene_tracker, test_db):
        """Test duration tracking on a single camera."""
        base_ts = int(time.time())
        
        # Person appears at T+0
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Keep person visible (update at T+5 minutes so they're still active)
        query_ts = base_ts + 300  # 5 minutes later
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=query_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Check duration after 5 minutes
        duration = scene_tracker.get_visitor_presence_duration(
            test_db,
            visitor_id="visitor_001",
            now_ts=query_ts,
        )
        
        assert duration == 300  # 5 minutes
    
    def test_cross_camera_continuous_duration(self, scene_tracker, test_db):
        """Test duration persists when person moves between cameras."""
        base_ts = int(time.time())
        
        # Person appears on camera 1 at T+0
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person still on camera 1 at T+1 minute (to keep camera 1 track active longer)
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts + 60,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person appears on camera 2 at T+62 seconds (within grace period of camera 1)
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=base_ts + 62,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Keep person visible on camera 2 at T+7 minutes
        query_ts = base_ts + 420
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=query_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Check duration at T+7 minutes (person on camera 2)
        duration = scene_tracker.get_visitor_presence_duration(
            test_db,
            visitor_id="visitor_001",
            now_ts=query_ts,
        )
        
        # Should be 7 minutes total, not ~6 minutes from camera 2
        assert duration == 420
    
    def test_duration_resets_after_leaving(self, scene_tracker, test_db):
        """Test duration resets when person leaves all cameras."""
        base_ts = int(time.time())
        grace_period = 6
        
        # Day 1: Person on camera 1 at T+0
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person leaves - update with empty observations after grace period
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts + grace_period + 1,
            observations=[],  # No one visible
        )
        
        # Day 2: Person returns 1 hour later
        new_session_ts = base_ts + 3600
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=new_session_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Keep person visible 5 minutes into new session
        query_ts = new_session_ts + 300
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=query_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Check duration 5 minutes into new session
        duration = scene_tracker.get_visitor_presence_duration(
            test_db,
            visitor_id="visitor_001",
            now_ts=query_ts,
        )
        
        # Should be 5 minutes, not 1 hour + 5 minutes
        assert duration == 300
    
    def test_duration_zero_for_inactive_visitor(self, scene_tracker, test_db):
        """Test duration is 0 for visitors not currently active."""
        now = int(time.time())
        
        duration = scene_tracker.get_visitor_presence_duration(
            test_db,
            visitor_id="visitor_999",
            now_ts=now,
        )
        
        assert duration == 0
    
    def test_all_visitor_durations(self, scene_tracker, test_db):
        """Test getting durations for all active visitors."""
        base_ts = int(time.time())
        
        # Visitor 1 on camera 1 at T+0
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Visitor 2 on camera 2 at T+2 minutes
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=base_ts + 120,
            observations=[
                Observation(
                    track_type="person",
                    box=(300, 100, 400, 300),
                    visitor_id="visitor_002",
                )
            ],
        )
        
        # Keep both visible at T+5 minutes
        query_ts = base_ts + 300
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=query_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                ),
            ],
        )
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=query_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(300, 100, 400, 300),
                    visitor_id="visitor_002",
                ),
            ],
        )
        
        # Check all durations at T+5 minutes
        durations = scene_tracker.get_all_visitor_presence_durations(
            test_db,
            now_ts=query_ts,
        )
        
        assert len(durations) == 2
        assert durations["visitor_001"] == 300  # 5 minutes
        assert durations["visitor_002"] == 180  # 3 minutes
    
    def test_duration_with_camera_handoff(self, scene_tracker, test_db):
        """Test duration during grace period camera handoff."""
        base_ts = int(time.time())
        
        # Person on camera 1 at T+0
        scene_tracker.update(
            test_db,
            camera_id=1,
            now_ts=base_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(100, 100, 200, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Person appears on camera 2 at T+3 seconds (still visible on camera 1 within grace period)
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=base_ts + 3,
            observations=[
                Observation(
                    track_type="person",
                    box=(300, 100, 400, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Keep person visible on camera 2 at T+10 seconds
        query_ts = base_ts + 10
        scene_tracker.update(
            test_db,
            camera_id=2,
            now_ts=query_ts,
            observations=[
                Observation(
                    track_type="person",
                    box=(300, 100, 400, 300),
                    visitor_id="visitor_001",
                )
            ],
        )
        
        # Check duration at T+10 seconds
        duration = scene_tracker.get_visitor_presence_duration(
            test_db,
            visitor_id="visitor_001",
            now_ts=query_ts,
        )
        
        # Should use earliest first_seen (camera 1) = 10 seconds
        assert duration == 10

