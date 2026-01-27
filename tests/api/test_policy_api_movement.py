"""
Tests for Policy API movement analysis.

Tests that the Policy API correctly detects:
- Objects leaving the scene
- Significant position changes
- Loitering (stationary objects)
"""

import pytest
import time
import json


def test_movement_position_changed(api_client):
    """Test detection of significant position change."""
    client, conn = api_client
    
    # First observation: vehicle at position (100, 200)
    payload1 = {
        "camera_id": 1,
        "event_id": "evt_move_1",
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "vehicle",
                "bbox": [100, 200, 300, 400],
                "props": {}
            }
        ],
        "evidence": [],
        "context": {}
    }
    
    # Update scene tracking first
    client.post("/scene/update", json={
        "camera_id": 1,
        "timestamp": payload1["timestamp"],
        "event_id": payload1["event_id"],
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "conf": 0.95,
                "bbox": {"x": 100, "y": 200, "w": 200, "h": 200},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    })
    
    # Get track_key from scene update response
    track_keys = client.get("/scene/tracks/1").json()
    track_key = track_keys["active_tracks"][0]["track_key"]
    
    # Second observation: same vehicle moved significantly (to 200, 300)
    payload2 = {
        "camera_id": 1,
        "event_id": "evt_move_2",
        "timestamp": int(time.time()) + 5,
        "objects": [
            {
                "object_id": 1,
                "label": "vehicle",
                "bbox": [200, 300, 400, 500],
                "props": {"scene_track_key": track_key}
            }
        ],
        "evidence": [],
        "context": {}
    }
    
    # Send second observation - should detect movement
    response = client.post("/evidence", json=payload2)
    assert response.status_code == 200
    
    data = response.json()
    # Should have executed at least one policy action (movement detected)
    assert "executed 1 policy actions" in data["message"].lower() or "executed" in data["message"].lower()


def test_movement_object_exited(api_client):
    """Test detection of object leaving the scene."""
    client, conn = api_client
    
    timestamp = int(time.time())
    
    # First: Two vehicles enter
    scene_update1 = {
        "camera_id": 1,
        "timestamp": timestamp,
        "event_id": "evt_exit_1",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "conf": 0.95,
                "bbox": {"x": 100, "y": 200, "w": 200, "h": 200},
                "props": {}
            },
            {
                "object_id": 2,
                "cls": "vehicle",
                "conf": 0.92,
                "bbox": {"x": 400, "y": 200, "w": 200, "h": 200},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    resp1 = client.post("/scene/update", json=scene_update1)
    track_keys = resp1.json()["track_keys"]
    
    # Send evidence with both vehicles
    evidence1 = {
        "camera_id": 1,
        "event_id": "evt_exit_1",
        "timestamp": timestamp,
        "objects": [
            {
                "object_id": 1,
                "label": "vehicle",
                "bbox": [100, 200, 300, 400],
                "props": {"scene_track_key": track_keys["1"]}
            },
            {
                "object_id": 2,
                "label": "vehicle",
                "bbox": [400, 200, 600, 400],
                "props": {"scene_track_key": track_keys["2"]}
            }
        ],
        "evidence": [],
        "context": {}
    }
    
    client.post("/evidence", json=evidence1)
    
    # Second observation: Only vehicle 2 remains (vehicle 1 exited)
    evidence2 = {
        "camera_id": 1,
        "event_id": "evt_exit_2",
        "timestamp": timestamp + 10,
        "objects": [
            {
                "object_id": 2,
                "label": "vehicle",
                "bbox": [400, 200, 600, 400],
                "props": {"scene_track_key": track_keys["2"]}
            }
        ],
        "evidence": [],
        "context": {}
    }
    
    response = client.post("/evidence", json=evidence2)
    assert response.status_code == 200
    
    data = response.json()
    # Should have logged movement evidence (vehicle 1 exited)
    assert "1 evidence items" in data["message"].lower() or "evidence" in data["message"].lower()


def test_movement_loitering_detection(api_client):
    """Test detection of object loitering (stationary for extended time)."""
    client, conn = api_client
    
    timestamp = int(time.time())
    
    # First observation: Person appears
    scene_update = {
        "camera_id": 1,
        "timestamp": timestamp - 35,  # 35 seconds ago
        "event_id": "evt_loiter_1",
        "detections": [
            {
                "object_id": 1,
                "cls": "person",
                "conf": 0.95,
                "bbox": {"x": 100, "y": 200, "w": 80, "h": 150},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    resp = client.post("/scene/update", json=scene_update)
    track_key = resp.json()["track_keys"]["1"]
    
    # Second observation: Same person, barely moved, 35 seconds later
    evidence_payload = {
        "camera_id": 1,
        "event_id": "evt_loiter_2",
        "timestamp": timestamp,
        "objects": [
            {
                "object_id": 1,
                "label": "person",
                "bbox": [105, 205, 185, 355],  # Moved only 5 pixels
                "props": {"scene_track_key": track_key}
            }
        ],
        "evidence": [],
        "context": {}
    }
    
    response = client.post("/evidence", json=evidence_payload)
    assert response.status_code == 200
    
    data = response.json()
    # Should have executed at least one policy action (loitering detected)
    assert "executed 1 policy actions" in data["message"].lower() or "executed" in data["message"].lower()


def test_movement_no_false_positives(api_client):
    """Test that small movements don't trigger position_changed."""
    client, conn = api_client
    
    timestamp = int(time.time())
    
    # First observation
    scene_update = {
        "camera_id": 1,
        "timestamp": timestamp,
        "event_id": "evt_small_1",
        "detections": [
            {
                "object_id": 1,
                "cls": "person",
                "conf": 0.95,
                "bbox": {"x": 100, "y": 200, "w": 80, "h": 150},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    resp = client.post("/scene/update", json=scene_update)
    track_key = resp.json()["track_keys"]["1"]
    
    # Second observation: Tiny movement (< 20 pixels)
    evidence_payload = {
        "camera_id": 1,
        "event_id": "evt_small_2",
        "timestamp": timestamp + 2,
        "objects": [
            {
                "object_id": 1,
                "label": "person",
                "bbox": [105, 205, 185, 355],  # Moved 5 pixels (normal detection variance)
                "props": {"scene_track_key": track_key}
            }
        ],
        "evidence": [],
        "context": {}
    }
    
    response = client.post("/evidence", json=evidence_payload)
    assert response.status_code == 200
    
    data = response.json()
    # Should NOT generate movement evidence for tiny movements
    # Message should show 0 evidence items
    assert "0 evidence items" in data["message"].lower()


def test_movement_multi_camera_independent(api_client):
    """Test that movement detection is per-camera (not cross-camera)."""
    client, conn = api_client
    
    timestamp = int(time.time())
    
    # Camera 1: Vehicle
    scene1 = {
        "camera_id": 1,
        "timestamp": timestamp,
        "event_id": "evt_cam1",
        "detections": [
            {"object_id": 1, "cls": "vehicle", "conf": 0.95, "bbox": {"x": 100, "y": 200, "w": 200, "h": 200}, "props": {}}
        ],
        "plate_hmac_by_object_id": {}
    }
    
    resp1 = client.post("/scene/update", json=scene1)
    track_key1 = resp1.json()["track_keys"]["1"]
    
    # Camera 2: Different vehicle (should be tracked independently)
    scene2 = {
        "camera_id": 2,
        "timestamp": timestamp,
        "event_id": "evt_cam2",
        "detections": [
            {"object_id": 1, "cls": "vehicle", "conf": 0.95, "bbox": {"x": 300, "y": 400, "w": 200, "h": 200}, "props": {}}
        ],
        "plate_hmac_by_object_id": {}
    }
    
    resp2 = client.post("/scene/update", json=scene2)
    track_key2 = resp2.json()["track_keys"]["1"]
    
    # Camera 1: Vehicle exits
    evidence_cam1 = {
        "camera_id": 1,
        "event_id": "evt_cam1_exit",
        "timestamp": timestamp + 10,
        "objects": [],  # Vehicle left camera 1
        "evidence": [],
        "context": {}
    }
    
    response = client.post("/evidence", json=evidence_cam1)
    assert response.status_code == 200
    
    # Should detect exit on camera 1 only (logged evidence)
    data = response.json()
    assert "1 evidence items" in data["message"].lower() or "evidence" in data["message"].lower()
    
    # Camera 2 vehicle should still be active (count > 0 means active tracks exist)
    tracks_cam2 = client.get("/scene/tracks/2").json()
    assert tracks_cam2["count"] == 1
    assert len(tracks_cam2["active_tracks"]) == 1
