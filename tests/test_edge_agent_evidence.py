"""
Tests for edge agent evidence submission to Policy API.

NOTE: This test is now deprecated as the unified edge agent (edge/agent/)
has replaced the old doorbell-agent. The edge agent sends observations
via send_to_policy_api() in edge/agent/main.py.

Skipping this test until we create new edge agent integration tests.
"""

import pytest

pytest.skip("Deprecated - edge agent unified, needs new tests", allow_module_level=True)


class TestEdgeAgentEvidenceSubmission:
    """Test edge agent sends evidence correctly to Policy API."""
    
    @patch('requests.post')
    def test_send_evidence_basic(self, mock_post):
        """Test basic evidence submission with vision objects and evidence."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "received": True,
            "event_id": "evt_123",
            "message": "Evidence logged successfully"
        }
        mock_post.return_value = mock_response
        
        # Create test vision result
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=True,
            package_box=False,
            vehicle_present=False,
            dog_present=False,
            objects=[
                SceneObject(
                    object_id=1,
                    label="person",
                    box=(100, 200, 180, 350),
                    props={"color": "tan", "scene_track_key": "person_abc123"}
                )
            ],
            evidence=[
                Evidence(source="vision", feature="person_present", value="true", conf=0.95),
                Evidence(source="vision", feature="color", value="tan", conf=0.8, object_id=1)
            ]
        )
        
        # Call function
        result = send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_123",
            camera_id=1,
            timestamp=1737585600,
            transcript=None
        )
        
        # Verify it returned True
        assert result is True
        
        # Verify requests.post was called
        assert mock_post.called
        assert mock_post.call_count == 1
        
        # Get the actual call arguments
        call_args = mock_post.call_args
        url = call_args[0][0]
        payload = call_args[1]['json']
        
        # Verify URL
        assert url == "http://localhost:8000/evidence"
        
        # Verify payload structure
        assert payload["camera_id"] == 1
        assert payload["event_id"] == "evt_123"
        assert payload["timestamp"] == 1737585600
        
        # Verify objects
        assert len(payload["objects"]) == 1
        assert payload["objects"][0]["object_id"] == 1
        assert payload["objects"][0]["label"] == "person"
        assert payload["objects"][0]["bbox"] == [100, 200, 180, 350]
        assert payload["objects"][0]["props"]["color"] == "tan"
        assert payload["objects"][0]["props"]["scene_track_key"] == "person_abc123"
        
        # Verify evidence
        assert len(payload["evidence"]) == 2
        assert payload["evidence"][0]["source"] == "vision"
        assert payload["evidence"][0]["feature"] == "person_present"
        assert payload["evidence"][0]["value"] == "true"
        assert payload["evidence"][0]["conf"] == 0.95
        
        # Verify context
        assert payload["context"]["mode"] == "WORKING"
        assert payload["context"]["person_present"] is True
        assert payload["context"]["vehicle_present"] is False
        
        # Verify no transcript
        assert "transcript" not in payload
    
    @patch('requests.post')
    def test_send_evidence_with_transcript(self, mock_post):
        """Test evidence submission includes audio transcript."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        
        # Setup mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"received": True, "event_id": "evt_456", "message": "OK"}
        mock_post.return_value = mock_response
        
        # Create vision result
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=True,
            package_box=False,
            vehicle_present=False,
            dog_present=False,
            objects=[],
            evidence=[
                Evidence(source="ocr", feature="token", value="sheriff", conf=0.9)
            ]
        )
        
        # Call with transcript
        result = send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_456",
            camera_id=1,
            timestamp=1737585600,
            transcript="I'm here to check on a noise complaint"
        )
        
        assert result is True
        
        # Verify transcript was included
        payload = mock_post.call_args[1]['json']
        assert payload["transcript"] == "I'm here to check on a noise complaint"
    
    @patch('requests.post')
    def test_send_evidence_multiple_objects(self, mock_post):
        """Test evidence submission with multiple objects and rich evidence."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        
        # Setup mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"received": True, "event_id": "evt_789", "message": "OK"}
        mock_post.return_value = mock_response
        
        # Create vision with multiple objects
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=True,
            package_box=False,
            vehicle_present=True,
            dog_present=False,
            objects=[
                SceneObject(
                    object_id=1,
                    label="person",
                    box=(100, 200, 180, 350),
                    props={"color": "tan", "scene_track_key": "person_abc"}
                ),
                SceneObject(
                    object_id=2,
                    label="vehicle",
                    box=(50, 100, 350, 300),
                    props={"color": "black", "scene_track_key": "vehicle_xyz"}
                )
            ],
            evidence=[
                Evidence(source="vision", feature="person_present", value="true", conf=0.95),
                Evidence(source="vision", feature="vehicle_present", value="true", conf=0.92),
                Evidence(source="vision", feature="uniform_color", value="tan", conf=0.8, object_id=1),
                Evidence(source="scene", feature="vehicle_entered", value="vehicle_xyz", conf=1.0),
                Evidence(source="scene", feature="person_count", value="1", conf=1.0),
                Evidence(source="ocr", feature="token", value="sheriff", conf=0.9)
            ]
        )
        
        # Call function
        result = send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_789",
            camera_id=1,
            timestamp=1737585600,
            transcript="Official business"
        )
        
        assert result is True
        
        # Verify payload
        payload = mock_post.call_args[1]['json']
        
        # Check objects
        assert len(payload["objects"]) == 2
        assert payload["objects"][0]["label"] == "person"
        assert payload["objects"][1]["label"] == "vehicle"
        
        # Check evidence
        assert len(payload["evidence"]) == 6
        evidence_features = [ev["feature"] for ev in payload["evidence"]]
        assert "person_present" in evidence_features
        assert "vehicle_entered" in evidence_features
        assert "token" in evidence_features
        
        # Check context flags
        assert payload["context"]["person_present"] is True
        assert payload["context"]["vehicle_present"] is True
    
    @patch('requests.post')
    def test_send_evidence_empty_scene(self, mock_post):
        """Test evidence submission with empty scene (no objects detected)."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        
        # Setup mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"received": True, "event_id": "evt_empty", "message": "OK"}
        mock_post.return_value = mock_response
        
        # Create empty vision result
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=False,
            package_box=False,
            vehicle_present=False,
            dog_present=False,
            objects=[],
            evidence=[
                Evidence(source="scene", feature="vehicle_count", value="0", conf=1.0),
                Evidence(source="scene", feature="person_count", value="0", conf=1.0)
            ]
        )
        
        # Call function
        result = send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_empty",
            camera_id=2,
            timestamp=1737585600,
            transcript=None
        )
        
        assert result is True
        
        # Verify payload
        payload = mock_post.call_args[1]['json']
        assert len(payload["objects"]) == 0
        assert len(payload["evidence"]) == 2
        assert payload["context"]["person_present"] is False
        assert payload["context"]["vehicle_present"] is False
    
    @patch('requests.post')
    def test_send_evidence_api_failure_warn_only(self, mock_post):
        """Test graceful handling when Policy API is unavailable (warn_only mode)."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        import requests
        
        # Simulate API failure
        mock_post.side_effect = requests.RequestException("Connection refused")
        
        # Create minimal vision result
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=False,
            package_box=False,
            vehicle_present=False,
            dog_present=False,
            objects=[],
            evidence=[]
        )
        
        # Should return False but not raise exception (warn_only=True in config)
        result = send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_fail",
            camera_id=1,
            timestamp=1737585600,
            transcript=None
        )
        
        assert result is False
        assert mock_post.called
    
    @patch('requests.post')
    def test_send_evidence_filters_none_object_ids(self, mock_post):
        """Test that objects with None object_id are filtered out."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        
        # Setup mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"received": True, "event_id": "evt_filter", "message": "OK"}
        mock_post.return_value = mock_response
        
        # Create vision with some objects having None object_id
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=True,
            package_box=False,
            vehicle_present=False,
            dog_present=False,
            objects=[
                SceneObject(object_id=1, label="person", box=(100, 200, 180, 350), props={}),
                SceneObject(object_id=None, label="noise", box=(0, 0, 10, 10), props={}),  # Should be filtered
                SceneObject(object_id=2, label="package", box=(150, 250, 200, 280), props={})
            ],
            evidence=[]
        )
        
        # Call function
        result = send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_filter",
            camera_id=1,
            timestamp=1737585600,
            transcript=None
        )
        
        assert result is True
        
        # Verify only objects with valid object_id were sent
        payload = mock_post.call_args[1]['json']
        assert len(payload["objects"]) == 2
        assert all(obj["object_id"] is not None for obj in payload["objects"])
        object_ids = [obj["object_id"] for obj in payload["objects"]]
        assert 1 in object_ids
        assert 2 in object_ids
    
    @patch('requests.post')
    def test_send_evidence_timeout_setting(self, mock_post):
        """Test that API timeout from config is used."""
        send_evidence_to_policy_api = orchestrator.send_evidence_to_policy_api
        
        # Setup mock
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"received": True, "event_id": "evt_timeout", "message": "OK"}
        mock_post.return_value = mock_response
        
        # Create minimal vision
        vision = VisionResult(
            snapshot_path="/path/to/snapshot.jpg",
            detections=[],
            person_present=False,
            package_box=False,
            vehicle_present=False,
            dog_present=False,
            objects=[],
            evidence=[]
        )
        
        # Call function
        send_evidence_to_policy_api(
            vision=vision,
            event_id="evt_timeout",
            camera_id=1,
            timestamp=1737585600,
            transcript=None
        )
        
        # Verify timeout was passed
        call_kwargs = mock_post.call_args[1]
        assert 'timeout' in call_kwargs
        assert call_kwargs['timeout'] == 5.0  # From config.yaml
