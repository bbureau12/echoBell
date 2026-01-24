"""
Tests for Policy API /evidence endpoint.

The edge device sends observations (objects + evidence) to the Policy API.
The Policy API logs the evidence and makes decisions (future implementation).
"""

import pytest
import time


def test_evidence_endpoint_basic(api_client):
    """Test basic evidence submission from edge device."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "event_id": "test_evt_001",
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "person",
                "bbox": [100, 200, 180, 350],
                "props": {"color": "tan"}
            }
        ],
        "evidence": [
            {"source": "vision", "feature": "person_present", "value": "true", "conf": 0.95},
            {"source": "vision", "feature": "color", "value": "tan", "conf": 0.8, "object_id": 1}
        ]
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True
    assert data["event_id"] == "test_evt_001"
    assert "message" in data


def test_evidence_with_transcript(api_client):
    """Test evidence submission with audio transcript."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "event_id": "test_evt_002",
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "person",
                "bbox": [100, 200, 180, 350],
                "props": {"color": "tan"}
            }
        ],
        "evidence": [
            {"source": "vision", "feature": "person_present", "value": "true", "conf": 0.95},
            {"source": "vision", "feature": "uniform_color", "value": "tan", "conf": 0.8},
            {"source": "ocr", "feature": "token", "value": "sheriff", "conf": 0.9}
        ],
        "transcript": "I'm here to check on a noise complaint"
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True
    assert data["event_id"] == "test_evt_002"


def test_evidence_empty_observations(api_client):
    """Test evidence submission with no objects or evidence (empty scene)."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "event_id": "test_evt_003",
        "timestamp": int(time.time()),
        "objects": [],
        "evidence": []
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True


def test_evidence_with_context(api_client):
    """Test evidence submission with additional context metadata."""
    client, conn = api_client
    
    payload = {
        "camera_id": 1,
        "event_id": "test_evt_004",
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "vehicle",
                "bbox": [50, 100, 350, 300],
                "props": {"scene_track_key": "vehicle_abc123"}
            }
        ],
        "evidence": [
            {"source": "vision", "feature": "vehicle_present", "value": "true", "conf": 0.95},
            {"source": "scene", "feature": "vehicle_entered", "value": "vehicle_abc123", "conf": 1.0}
        ],
        "context": {
            "mode": "guard",
            "motion_detected": True,
            "prior_events": ["evt_001", "evt_002"]
        }
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True


def test_evidence_multiple_objects(api_client):
    """Test evidence submission with multiple observed objects."""
    client, conn = api_client
    
    payload = {
        "camera_id": 2,
        "event_id": "test_evt_005",
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "person",
                "bbox": [100, 200, 180, 350],
                "props": {"color": "brown"}
            },
            {
                "object_id": 2,
                "label": "vehicle",
                "bbox": [50, 100, 350, 300],
                "props": {"color": "black"}
            },
            {
                "object_id": 3,
                "label": "package",
                "bbox": [150, 250, 200, 280],
                "props": {}
            }
        ],
        "evidence": [
            {"source": "vision", "feature": "person_present", "value": "true", "conf": 0.95},
            {"source": "vision", "feature": "vehicle_present", "value": "true", "conf": 0.92},
            {"source": "vision", "feature": "package_box", "value": "true", "conf": 0.85},
            {"source": "scene", "feature": "person_count", "value": "1", "conf": 1.0},
            {"source": "scene", "feature": "vehicle_count", "value": "1", "conf": 1.0}
        ]
    }
    
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["received"] is True
    assert "3" in data["message"] or "5" in data["message"]  # Mentions object or evidence count
