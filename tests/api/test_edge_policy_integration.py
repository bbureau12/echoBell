"""
Integration tests for edge agent -> Policy API communication.

Tests the complete flow of edge device sending observations to Policy API.
"""

import pytest
import time
from packages.common.types import VisionResult, SceneObject, Evidence


def test_edge_sends_complete_observations(api_client):
    """Test edge agent sending complete observations (objects + evidence + transcript)."""
    client, conn = api_client
    
    # Simulate what edge agent would send after vision + ASR
    payload = {
        "camera_id": 1,
        "event_id": "evt_1737585600_1",
        "timestamp": 1737585600,
        "objects": [
            {
                "object_id": 1,
                "label": "person",
                "bbox": [100, 200, 180, 350],
                "props": {
                    "color": "tan",
                    "scene_track_key": "person_abc123"
                }
            },
            {
                "object_id": 2,
                "label": "vehicle",
                "bbox": [50, 100, 350, 300],
                "props": {
                    "color": "black",
                    "scene_track_key": "vehicle_xyz789"
                }
            }
        ],
        "evidence": [
            {"source": "vision", "feature": "person_present", "value": "true", "conf": 0.95},
            {"source": "vision", "feature": "vehicle_present", "value": "true", "conf": 0.92},
            {"source": "vision", "feature": "uniform_color", "value": "tan", "conf": 0.8, "object_id": 1},
            {"source": "ocr", "feature": "token", "value": "sheriff", "conf": 0.9},
            {"source": "scene", "feature": "vehicle_entered", "value": "vehicle_xyz789", "conf": 1.0},
            {"source": "scene", "feature": "person_count", "value": "1", "conf": 1.0},
        ],
        "transcript": "I'm here to check on a noise complaint",
        "context": {
            "mode": "guard",
            "person_present": True,
            "vehicle_present": True,
            "package_box": False
        }
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True
    assert data["event_id"] == "evt_1737585600_1"


def test_edge_sends_vision_only(api_client):
    """Test edge agent sending just vision observations (no audio yet)."""
    client, conn = api_client
    
    payload = {
        "camera_id": 2,
        "event_id": "evt_1737585601_2",
        "timestamp": 1737585601,
        "objects": [
            {
                "object_id": 1,
                "label": "package",
                "bbox": [150, 250, 200, 280],
                "props": {}
            }
        ],
        "evidence": [
            {"source": "vision", "feature": "package_box", "value": "true", "conf": 0.85},
            {"source": "scene", "feature": "package_count", "value": "1", "conf": 1.0}
        ],
        "context": {
            "mode": "guard",
            "person_present": False,
            "vehicle_present": False,
            "package_box": True
        }
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True


def test_edge_multi_camera_observations(api_client):
    """Test observations from multiple edge devices (different cameras)."""
    client, conn = api_client
    
    # Camera 1 observation
    payload_cam1 = {
        "camera_id": 1,
        "event_id": "evt_1737585602_1",
        "timestamp": 1737585602,
        "objects": [{"object_id": 1, "label": "person", "bbox": [100, 200, 180, 350], "props": {}}],
        "evidence": [{"source": "vision", "feature": "person_present", "value": "true", "conf": 0.95}],
        "context": {"mode": "guard"}
    }
    
    # Camera 2 observation (same event, different camera)
    payload_cam2 = {
        "camera_id": 2,
        "event_id": "evt_1737585602_2",
        "timestamp": 1737585603,
        "objects": [{"object_id": 1, "label": "person", "bbox": [120, 210, 190, 360], "props": {}}],
        "evidence": [{"source": "vision", "feature": "person_present", "value": "true", "conf": 0.93}],
        "context": {"mode": "guard"}
    }
    
    response1 = client.post("/evidence", json=payload_cam1)
    assert response1.status_code == 200
    
    response2 = client.post("/evidence", json=payload_cam2)
    assert response2.status_code == 200
    
    # Both should be received successfully
    assert response1.json()["received"] is True
    assert response2.json()["received"] is True


def test_edge_sends_empty_scene(api_client):
    """Test edge agent reporting empty scene (motion trigger but nothing detected)."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "event_id": "evt_1737585604_1",
        "timestamp": 1737585604,
        "objects": [],
        "evidence": [
            {"source": "scene", "feature": "vehicle_count", "value": "0", "conf": 1.0},
            {"source": "scene", "feature": "person_count", "value": "0", "conf": 1.0}
        ],
        "context": {
            "mode": "guard",
            "person_present": False,
            "vehicle_present": False,
            "package_box": False
        }
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True
