"""
Tests for Scheduler Daemon

Tests the camera registry, trigger logic, and scheduler without
actually making HTTP requests to edge cameras.
"""

import pytest
import sqlite3
import time
import os
import sys
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

# Import scheduler modules
import importlib.util
spec = importlib.util.spec_from_file_location(
    "scheduler",
    os.path.join(PROJECT_ROOT, "central", "scheduler", "scheduler.py")
)
scheduler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduler_module)

CameraRegistry = scheduler_module.CameraRegistry
CameraTrigger = scheduler_module.CameraTrigger


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database with edge_cameras table."""
    db_path = str(tmp_path / "test_scheduler.db")
    conn = sqlite3.connect(db_path)
    
    # Create table with full schema
    conn.executescript("""
        CREATE TABLE edge_cameras (
            camera_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            endpoint_url TEXT NOT NULL,
            enabled BOOLEAN DEFAULT 1,
            capture_interval_s INTEGER DEFAULT 60,
            last_capture_ts INTEGER,
            last_success_ts INTEGER,
            consecutive_failures INTEGER DEFAULT 0,
            metadata TEXT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );
        
        INSERT INTO edge_cameras (camera_id, name, endpoint_url, enabled, capture_interval_s, metadata) VALUES
        (1, 'Test Camera 1', 'http://localhost:5001', 1, 60, '{}'),
        (2, 'Test Camera 2', 'http://localhost:5002', 1, 30, '{}'),
        (3, 'Disabled Camera', 'http://localhost:5003', 0, 60, '{}');
    """)
    conn.commit()
    conn.close()
    
    return db_path


class TestCameraRegistry:
    """Test the CameraRegistry class."""
    
    def test_refresh_loads_enabled_cameras(self, test_db):
        """Test that refresh() loads only enabled cameras."""
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.refresh()
        
        assert len(registry.cameras) == 2  # Only enabled cameras
        assert all(cam['enabled'] == 1 for cam in registry.cameras)
        assert registry.cameras[0]['name'] == 'Test Camera 1'
        assert registry.cameras[1]['name'] == 'Test Camera 2'
    
    def test_get_cameras_needing_capture(self, test_db):
        """Test identifying cameras that need capture."""
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.refresh()
        
        now = int(time.time())
        
        # All cameras should need capture (no last_capture_ts)
        cameras_due = registry.get_cameras_needing_capture(now)
        assert len(cameras_due) == 2
    
    def test_cameras_with_recent_capture_not_due(self, test_db):
        """Test that cameras with recent captures are not returned."""
        # Update camera 1 to have captured recently
        conn = sqlite3.connect(test_db)
        now = int(time.time())
        conn.execute("UPDATE edge_cameras SET last_capture_ts = ? WHERE camera_id = 1", (now,))
        conn.commit()
        conn.close()
        
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.refresh()
        
        # Only camera 2 should be due (camera 1 just captured)
        cameras_due = registry.get_cameras_needing_capture(now + 10)
        assert len(cameras_due) == 1
        assert cameras_due[0]['camera_id'] == 2
    
    def test_update_capture_status_success(self, test_db):
        """Test updating camera status after successful capture."""
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.update_capture_status(camera_id=1, success=True)
        
        # Verify database was updated
        conn = sqlite3.connect(test_db)
        row = conn.execute("""
            SELECT last_capture_ts, last_success_ts, consecutive_failures 
            FROM edge_cameras WHERE camera_id = 1
        """).fetchone()
        conn.close()
        
        assert row[0] is not None  # last_capture_ts set
        assert row[1] is not None  # last_success_ts set
        assert row[2] == 0  # consecutive_failures reset
    
    def test_update_capture_status_failure(self, test_db):
        """Test updating camera status after failed capture."""
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.update_capture_status(camera_id=1, success=False)
        
        # Verify database was updated
        conn = sqlite3.connect(test_db)
        row = conn.execute("""
            SELECT last_capture_ts, consecutive_failures 
            FROM edge_cameras WHERE camera_id = 1
        """).fetchone()
        conn.close()
        
        assert row[0] is not None  # last_capture_ts set
        assert row[1] == 1  # consecutive_failures incremented
    
    def test_max_consecutive_failures_filters_camera(self, test_db):
        """Test that cameras with too many failures are filtered out."""
        # Set camera 1 to have 5 consecutive failures
        conn = sqlite3.connect(test_db)
        conn.execute("UPDATE edge_cameras SET consecutive_failures = 5 WHERE camera_id = 1")
        conn.commit()
        conn.close()
        
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.refresh()
        
        now = int(time.time())
        cameras_due = registry.get_cameras_needing_capture(now)
        
        # Camera 1 should be filtered out due to failures
        assert len(cameras_due) == 1
        assert cameras_due[0]['camera_id'] == 2


class TestCameraTrigger:
    """Test the CameraTrigger class."""
    
    @patch('requests.post')
    def test_trigger_success(self, mock_post):
        """Test successful camera trigger."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        trigger = CameraTrigger(timeout_s=5.0, endpoint="/capture")
        camera = {
            'camera_id': 1,
            'name': 'Test Camera',
            'endpoint_url': 'http://localhost:5001'
        }
        
        success = trigger.trigger(camera)
        
        assert success is True
        assert mock_post.called
        
        # Verify correct URL
        call_args = mock_post.call_args
        assert call_args[0][0] == 'http://localhost:5001/capture'
        
        # Verify payload
        payload = call_args[1]['json']
        assert payload['trigger'] == 'scheduled'
        assert 'timestamp' in payload
    
    @patch('requests.post')
    def test_trigger_failure(self, mock_post):
        """Test camera trigger failure."""
        import requests
        mock_post.side_effect = requests.RequestException("Connection refused")
        
        trigger = CameraTrigger(timeout_s=5.0, endpoint="/capture")
        camera = {
            'camera_id': 1,
            'name': 'Test Camera',
            'endpoint_url': 'http://localhost:5001'
        }
        
        success = trigger.trigger(camera)
        
        assert success is False
    
    @patch('requests.post')
    def test_trigger_timeout(self, mock_post):
        """Test camera trigger timeout."""
        import requests
        mock_post.side_effect = requests.Timeout("Request timeout")
        
        trigger = CameraTrigger(timeout_s=5.0, endpoint="/capture")
        camera = {
            'camera_id': 1,
            'name': 'Test Camera',
            'endpoint_url': 'http://localhost:5001'
        }
        
        success = trigger.trigger(camera)
        
        assert success is False


class TestSchedulerIntegration:
    """Integration tests for scheduler behavior."""
    
    def test_per_camera_intervals(self, test_db):
        """Test that cameras use their individual capture intervals."""
        registry = CameraRegistry(db_path=test_db, refresh_interval_s=60)
        registry.refresh()
        
        now = int(time.time())
        
        # Update both cameras to have just captured
        conn = sqlite3.connect(test_db)
        conn.execute("UPDATE edge_cameras SET last_capture_ts = ? WHERE enabled = 1", (now,))
        conn.commit()
        conn.close()
        
        registry.refresh()
        
        # 20 seconds later: camera 2 (30s interval) not due, camera 1 (60s interval) not due
        cameras_due = registry.get_cameras_needing_capture(now + 20)
        assert len(cameras_due) == 0
        
        # 31 seconds later: camera 2 (30s interval) IS due, camera 1 (60s interval) not due
        cameras_due = registry.get_cameras_needing_capture(now + 31)
        assert len(cameras_due) == 1
        assert cameras_due[0]['camera_id'] == 2
        
        # 61 seconds later: both cameras due
        cameras_due = registry.get_cameras_needing_capture(now + 61)
        assert len(cameras_due) == 2
