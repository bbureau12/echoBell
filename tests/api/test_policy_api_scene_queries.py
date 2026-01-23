"""
Integration tests for Policy API scene query endpoints.

Tests the read-only query endpoints:
- GET /scene/tracks/{camera_id} - All active tracks
- GET /scene/vehicles/{camera_id} - Active vehicles only
- GET /scene/people/{camera_id} - Active people only
- GET /scene/summary/{camera_id} - Scene summary
"""

import pytest
import time


def test_get_vehicles_empty(api_client):
    """Test getting vehicles when none are present."""
    client, conn = api_client
    
    response = client.get("/scene/vehicles/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["count"] == 0
    assert len(data["vehicles"]) == 0


def test_get_vehicles_after_update(api_client):
    """Test getting vehicles after adding one via scene update."""
    client, conn = api_client
    
    # Add a vehicle
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_vehicle",
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
    
    client.post("/scene/update", json=payload)
    
    # Query vehicles
    response = client.get("/scene/vehicles/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["count"] == 1
    assert len(data["vehicles"]) == 1
    
    # Verify vehicle structure
    vehicle = data["vehicles"][0]
    assert "track_id" in vehicle
    assert "track_key" in vehicle
    assert "first_seen_ts" in vehicle
    assert "last_seen_ts" in vehicle


def test_get_people_empty(api_client):
    """Test getting people when none are present."""
    client, conn = api_client
    
    response = client.get("/scene/people/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["count"] == 0
    assert len(data["people"]) == 0


def test_get_people_after_update(api_client):
    """Test getting people after adding one via scene update."""
    client, conn = api_client
    
    # Add a person
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_person",
        "detections": [
            {
                "object_id": 1,
                "cls": "person",
                "raw_class": "person",
                "conf": 0.88,
                "bbox": {"x": 250.0, "y": 300.0, "w": 80.0, "h": 150.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    client.post("/scene/update", json=payload)
    
    # Query people
    response = client.get("/scene/people/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["count"] == 1
    assert len(data["people"]) == 1
    
    # Verify person structure
    person = data["people"][0]
    assert "track_id" in person
    assert "track_key" in person


def test_get_scene_summary_empty(api_client):
    """Test scene summary when scene is empty."""
    client, conn = api_client
    
    response = client.get("/scene/summary/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["total_active"] == 0
    assert len(data["active_now"]) == 0
    assert "timestamp" in data


def test_get_scene_summary_with_objects(api_client):
    """Test scene summary with multiple objects."""
    client, conn = api_client
    
    # Add vehicle and person
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_summary",
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
    
    client.post("/scene/update", json=payload)
    
    # Get summary
    response = client.get("/scene/summary/1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["camera_id"] == 1
    assert data["total_active"] == 2
    assert data["active_now"]["vehicle"] == 1
    assert data["active_now"]["person"] == 1
    assert data["recent_activity_5min"]["vehicle"] == 1
    assert data["recent_activity_5min"]["person"] == 1


def test_vehicles_filtered_by_type(api_client):
    """Test that /scene/vehicles only returns vehicles, not people."""
    client, conn = api_client
    
    # Add both vehicle and person
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_filter",
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
    
    client.post("/scene/update", json=payload)
    
    # Query vehicles - should only get 1
    vehicles_response = client.get("/scene/vehicles/1")
    assert vehicles_response.json()["count"] == 1
    
    # Query people - should only get 1
    people_response = client.get("/scene/people/1")
    assert people_response.json()["count"] == 1


def test_multiple_cameras_independent_scenes(api_client):
    """Test that different cameras have independent scene tracking."""
    client, conn = api_client
    
    # Add vehicle to camera 1
    payload_cam1 = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_cam1_vehicle",
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
    
    # Add person to camera 2
    payload_cam2 = {
        "camera_id": 2,
        "timestamp": int(time.time()),
        "event_id": "test_cam2_person",
        "detections": [
            {
                "object_id": 1,
                "cls": "person",
                "raw_class": "person",
                "conf": 0.88,
                "bbox": {"x": 250.0, "y": 300.0, "w": 80.0, "h": 150.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    client.post("/scene/update", json=payload_cam1)
    client.post("/scene/update", json=payload_cam2)
    
    # Camera 1 should have vehicle, no people
    cam1_vehicles = client.get("/scene/vehicles/1").json()
    cam1_people = client.get("/scene/people/1").json()
    assert cam1_vehicles["count"] == 1
    assert cam1_people["count"] == 0
    
    # Camera 2 should have person, no vehicles
    cam2_vehicles = client.get("/scene/vehicles/2").json()
    cam2_people = client.get("/scene/people/2").json()
    assert cam2_vehicles["count"] == 0
    assert cam2_people["count"] == 1
