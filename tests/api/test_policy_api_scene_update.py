"""
Integration tests for Policy API /scene/update endpoint.

Tests scene tracking functionality via the REST API instead of
direct SceneTracker calls. This validates the full API integration.
"""

import pytest
import time


def test_health_endpoint(api_client):
    """Test that the health endpoint is working."""
    client, _ = api_client
    
    response = client.get("/health")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert "database" in data
    assert "scene_tracker" in data


def test_scene_update_single_vehicle(api_client, sample_detections):
    """Test scene update with a single vehicle detection."""
    client, conn = api_client
    
    # Send scene update
    response = client.post("/scene/update", json=sample_detections)
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify response structure
    assert "scene_evidence" in data
    assert "track_keys" in data
    assert "message" in data
    
    # Verify scene evidence was generated
    assert len(data["scene_evidence"]) > 0
    
    # Should have vehicle_entered evidence
    features = [ev["feature"] for ev in data["scene_evidence"]]
    assert "vehicle_entered" in features
    
    # Should have track key for the vehicle (object_id=1)
    # Note: JSON serialization converts int keys to strings
    assert "1" in data["track_keys"]
    # Track key matches the plate_hmac provided in sample_detections
    assert data["track_keys"]["1"] == "abc123def456789_test_plate_hmac"


def test_scene_update_multiple_objects(api_client):
    """Test scene update with multiple objects (vehicle + person)."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_multi_obj",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
                "props": {}
            },
            {
                "object_id": 2,
                "cls": "person",
                "raw_class": "person",
                "conf": 0.88,
                "bbox": {"x": 250.0, "y": 300.0, "w": 80.0, "h": 150.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    response = client.post("/scene/update", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    
    # Should have evidence for both objects
    assert len(data["scene_evidence"]) >= 2
    
    # Should have track keys for both (JSON serialization uses string keys)
    assert "1" in data["track_keys"]  # vehicle
    assert "2" in data["track_keys"]  # person


def test_get_active_tracks_empty(api_client):
    """Test getting active tracks when none exist."""
    client, conn = api_client
    
    response = client.get("/scene/tracks/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["count"] == 0
    assert len(data["active_tracks"]) == 0


def test_get_active_tracks_after_update(api_client, sample_detections):
    """Test getting active tracks after a scene update."""
    client, conn = api_client
    
    # First, send a scene update
    update_response = client.post("/scene/update", json=sample_detections)
    assert update_response.status_code == 200
    
    # Now get active tracks
    tracks_response = client.get("/scene/tracks/1")
    assert tracks_response.status_code == 200
    
    data = tracks_response.json()
    assert data["camera_id"] == 1
    assert data["count"] > 0
    assert len(data["active_tracks"]) > 0
    
    # Verify track structure
    first_track = data["active_tracks"][0]
    assert "track_id" in first_track
    assert "track_type" in first_track
    assert "track_key" in first_track
    assert "first_seen_ts" in first_track
    assert "last_seen_ts" in first_track


def test_scene_update_with_plate_hmac(api_client):
    """Test scene update with license plate HMAC."""
    client, conn = api_client
    
    plate_hmac = "abc123def456789_test_plate_hmac"
    
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_plate",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {
            "1": plate_hmac
        }
    }
    
    response = client.post("/scene/update", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    
    # Track key should include the plate HMAC (JSON uses string keys)
    assert "1" in data["track_keys"]
    assert plate_hmac in data["track_keys"]["1"]


def test_scene_update_multiple_cameras(api_client):
    """Test that scene tracking works independently for different cameras."""
    client, conn = api_client
    
    # Update for camera 1
    payload_cam1 = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_cam1",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    # Update for camera 2
    payload_cam2 = {
        "camera_id": 2,
        "timestamp": int(time.time()),
        "event_id": "test_cam2",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "truck",
                "conf": 0.93,
                "bbox": {"x": 150.0, "y": 250.0, "w": 350.0, "h": 250.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    # Send updates
    response1 = client.post("/scene/update", json=payload_cam1)
    response2 = client.post("/scene/update", json=payload_cam2)
    
    assert response1.status_code == 200
    assert response2.status_code == 200
    
    # Get tracks for each camera
    tracks1 = client.get("/scene/tracks/1").json()
    tracks2 = client.get("/scene/tracks/2").json()
    
    # Each camera should have 1 active track
    assert tracks1["count"] == 1
    assert tracks2["count"] == 1
    
    # Tracks should be independent (different track_keys)
    assert tracks1["active_tracks"][0]["track_key"] != tracks2["active_tracks"][0]["track_key"]


def test_scene_update_persistence(api_client):
    """Test that scene tracks persist in the database."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_persist",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    # Send update
    response = client.post("/scene/update", json=payload)
    assert response.status_code == 200
    
    # Query database directly
    cursor = conn.execute(
        "SELECT COUNT(*) FROM scene_tracks WHERE camera_id = 1 AND active = 1"
    )
    count = cursor.fetchone()[0]
    
    assert count == 1, "Scene track should be persisted in database"


def test_scene_update_invalid_camera_id(api_client):
    """Test scene update with invalid camera_id."""
    client, conn = api_client
    
    payload = {
        "camera_id": 999,  # Non-existent camera
        "timestamp": int(time.time()),
        "event_id": "test_invalid",
        "detections": [],
        "plate_hmac_by_object_id": {}
    }
    
    # Should still succeed (SceneTracker doesn't validate camera_id)
    response = client.post("/scene/update", json=payload)
    assert response.status_code == 200


def test_scene_update_empty_detections(api_client):
    """Test scene update with no detections (empty scene)."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_empty",
        "detections": [],
        "plate_hmac_by_object_id": {}
    }
    
    response = client.post("/scene/update", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    
    # Empty scene should have count evidence showing zero counts
    assert len(data["scene_evidence"]) >= 0  # May have count evidence
    # All counts should be zero
    for ev in data["scene_evidence"]:
        if ev["feature"].endswith("_count"):
            assert ev["value"] == "0", f"{ev['feature']} should be 0 for empty scene"
    assert len(data["track_keys"]) == 0
