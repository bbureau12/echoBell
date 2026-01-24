"""
Policy API Server - Centralized scene tracking and decision engine

This FastAPI service handles:
- Scene tracking across multiple cameras/edge devices
- Vehicle-person linkage
- Visit history and trust scoring
- Policy decisions and LLM integration
"""

import os
import sys
import sqlite3
import time
from typing import Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from packages.scene.scene_tracker import SceneTracker, build_observations_from_vision
from packages.common.types import VisionResult, SceneObject, Evidence
from packages.common.config_models import RetentionSettings

# Import policy management router
# Note: Uses dynamic import to handle file naming with dash
import importlib.util
POLICY_ROUTER_AVAILABLE = False
try:
    router_path = os.path.join(PROJECT_ROOT, "apps", "doorbell-agent", "api_policies.py")
    if os.path.exists(router_path):
        spec = importlib.util.spec_from_file_location("api_policies", router_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            policy_router = module.router
            POLICY_ROUTER_AVAILABLE = True
except Exception as e:
    print(f"[warning] Policy management router not available: {e}")

# Initialize FastAPI
app = FastAPI(
    title="EchoBell Policy API",
    description="Centralized scene tracking and decision engine for multi-camera doorbell system",
    version="1.0.0"
)

# Include policy management router if available
if POLICY_ROUTER_AVAILABLE:
    app.include_router(policy_router)
    print("[info] Policy management endpoints enabled at /policies/*")

# Configuration
DB_PATH = os.getenv("ECHOBELL_DB_PATH", os.path.join(PROJECT_ROOT, "data", "echoBell.db"))
retention = RetentionSettings()

# Initialize SceneTracker (stateful, persists across requests)
scene_tracker = SceneTracker(
    iou_match_threshold=0.30,
    grace_period_s=retention.scene_tracking_grace_period_s
)

# Database connection context manager
@contextmanager
def get_db():
    """Get database connection with proper cleanup."""
    conn = sqlite3.connect(DB_PATH)
    try:
        # Ensure schema exists
        scene_tracker.ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================================
# Request/Response Models
# ============================================================================

class BoundingBox(BaseModel):
    """Bounding box coordinates."""
    x: float
    y: float
    w: float
    h: float


class Detection(BaseModel):
    """Single object detection from edge device."""
    object_id: int
    cls: str  # Semantic class (person, vehicle, etc.)
    raw_class: Optional[str] = None  # YOLO raw class (car, truck, bicycle)
    conf: float
    bbox: BoundingBox
    props: dict = Field(default_factory=dict)


class SceneUpdateRequest(BaseModel):
    """Request to update scene tracking with new detections."""
    camera_id: int
    timestamp: int  # Unix timestamp in seconds
    event_id: str
    detections: list[Detection]
    plate_hmac_by_object_id: dict[str, str] = Field(default_factory=dict)  # Maps object_id (as str) to plate HMAC
    

class SceneEvidence(BaseModel):
    """Scene tracking evidence returned to edge."""
    source: str
    feature: str
    value: str
    conf: float
    object_id: Optional[int] = None


class SceneUpdateResponse(BaseModel):
    """Response from scene update with tracking results."""
    scene_evidence: list[SceneEvidence]
    track_keys: dict[int, str]  # Maps object_id to scene_track_key
    message: str = "Scene updated successfully"


class ObservedObject(BaseModel):
    """Object observed by edge device."""
    object_id: int
    label: str  # person, vehicle, package, etc.
    bbox: list[float]  # [x1, y1, x2, y2]
    props: dict = Field(default_factory=dict)  # color, scene_track_key, etc.


class EvidenceItem(BaseModel):
    """Single piece of evidence from edge device."""
    source: str  # vision, ocr, audio, scene, etc.
    feature: str  # person_present, token, vehicle_entered, etc.
    value: str
    conf: float
    object_id: Optional[int] = None


class ObservationRequest(BaseModel):
    """Evidence and observations from edge device sensor."""
    camera_id: int
    event_id: str
    timestamp: int  # Unix timestamp in seconds
    objects: list[ObservedObject] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    transcript: Optional[str] = None  # Audio transcript if available
    context: dict = Field(default_factory=dict)  # Additional metadata


class ObservationResponse(BaseModel):
    """Acknowledgment that evidence was received and logged."""
    received: bool = True
    event_id: str
    message: str = "Evidence logged successfully"


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "database": DB_PATH,
        "scene_tracker": {
            "iou_threshold": scene_tracker.iou_match_threshold,
            "grace_period_s": scene_tracker.grace_period_s
        }
    }


@app.post("/scene/update", response_model=SceneUpdateResponse)
async def update_scene(request: SceneUpdateRequest):
    """
    Update scene tracking with new detections from edge device.
    
    This endpoint:
    1. Receives detections from edge cameras
    2. Updates temporal scene tracking (vehicles entering/exiting)
    3. Links people to vehicles
    4. Returns scene evidence for intent classification
    """
    try:
        with get_db() as conn:
            # Convert request detections to VisionResult format
            vision_objects = []
            for det in request.detections:
                obj = SceneObject(
                    object_id=det.object_id,
                    label=det.cls,
                    box=(det.bbox.x, det.bbox.y, det.bbox.x + det.bbox.w, det.bbox.y + det.bbox.h),
                    props=det.props.copy() if det.props else {}
                )
                # Add additional properties
                obj.props["conf"] = det.conf
                if det.raw_class:
                    obj.props["raw_class"] = det.raw_class
                vision_objects.append(obj)
            
            # Create minimal VisionResult (just need objects for tracking)
            vision = VisionResult(
                snapshot_path="",  # Policy API doesn't receive images
                detections=[],  # Already processed into SceneObjects
                person_present=any(obj.label == "person" for obj in vision_objects),
                package_box=any(obj.label == "package" for obj in vision_objects),
                vehicle_present=any(obj.label == "vehicle" for obj in vision_objects),
                dog_present=any(obj.label == "dog" for obj in vision_objects),
                objects=vision_objects,
                evidence=[]
            )
            
            # Convert plate_hmac keys from str to int (JSON serializes int keys as strings)
            plate_hmac_by_object_id = {
                int(k): v for k, v in request.plate_hmac_by_object_id.items()
            }
            
            # Build observations for SceneTracker
            observations = build_observations_from_vision(
                vision, 
                plate_hmac_by_object_id=plate_hmac_by_object_id
            )
            
            # Update scene tracking
            scene_evidence, object_to_track = scene_tracker.update(
                conn,
                camera_id=request.camera_id,
                now_ts=request.timestamp,
                observations=observations,
                event_id=request.event_id
            )
            
            # Convert Evidence objects to SceneEvidence models
            scene_evidence_models = [
                SceneEvidence(
                    source=ev.source,
                    feature=ev.feature,
                    value=ev.value,
                    conf=ev.conf,
                    object_id=ev.object_id
                )
                for ev in scene_evidence
            ]
            
            # Convert object_to_track keys from str to int (SceneTracker uses str keys)
            track_keys = {int(k): v for k, v in (object_to_track or {}).items()}
            
            return SceneUpdateResponse(
                scene_evidence=scene_evidence_models,
                track_keys=track_keys,
                message=f"Processed {len(observations)} observations, generated {len(scene_evidence)} evidence"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene update failed: {str(e)}")


@app.get("/scene/tracks/{camera_id}")
async def get_active_tracks(camera_id: int):
    """Get currently active scene tracks for a camera."""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, track_type, track_key, first_seen_ts, last_seen_ts, 
                       last_box_json, raw_class, tags
                FROM scene_tracks
                WHERE camera_id = ? AND active = 1
                ORDER BY last_seen_ts DESC
                """,
                (camera_id,)
            )
            
            tracks = []
            for row in cursor.fetchall():
                tracks.append({
                    "track_id": row[0],
                    "track_type": row[1],
                    "track_key": row[2],
                    "first_seen_ts": row[3],
                    "last_seen_ts": row[4],
                    "bbox_json": row[5],
                    "raw_class": row[6],
                    "tags": row[7]
                })
            
            return {
                "camera_id": camera_id,
                "active_tracks": tracks,
                "count": len(tracks)
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get tracks: {str(e)}")


@app.get("/scene/vehicles/{camera_id}")
async def get_active_vehicles(camera_id: int):
    """Get currently active vehicles in scene for a camera."""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, track_key, first_seen_ts, last_seen_ts, 
                       last_box_json, raw_class, tags
                FROM scene_tracks
                WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
                ORDER BY last_seen_ts DESC
                """,
                (camera_id,)
            )
            
            vehicles = []
            for row in cursor.fetchall():
                vehicles.append({
                    "track_id": row[0],
                    "track_key": row[1],
                    "first_seen_ts": row[2],
                    "last_seen_ts": row[3],
                    "bbox_json": row[4],
                    "raw_class": row[5],
                    "tags": row[6]
                })
            
            return {
                "camera_id": camera_id,
                "vehicles": vehicles,
                "count": len(vehicles)
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get vehicles: {str(e)}")


@app.get("/scene/people/{camera_id}")
async def get_active_people(camera_id: int):
    """Get currently active people in scene for a camera."""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                """
                SELECT id, track_key, first_seen_ts, last_seen_ts, 
                       last_box_json, raw_class, tags
                FROM scene_tracks
                WHERE camera_id = ? AND track_type = 'person' AND active = 1
                ORDER BY last_seen_ts DESC
                """,
                (camera_id,)
            )
            
            people = []
            for row in cursor.fetchall():
                people.append({
                    "track_id": row[0],
                    "track_key": row[1],
                    "first_seen_ts": row[2],
                    "last_seen_ts": row[3],
                    "bbox_json": row[4],
                    "raw_class": row[5],
                    "tags": row[6]
                })
            
            return {
                "camera_id": camera_id,
                "people": people,
                "count": len(people)
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get people: {str(e)}")


@app.get("/scene/summary/{camera_id}")
async def get_scene_summary(camera_id: int):
    """Get a summary of the current scene for a camera."""
    try:
        with get_db() as conn:
            # Get counts by type
            cursor = conn.execute(
                """
                SELECT track_type, COUNT(*) as count
                FROM scene_tracks
                WHERE camera_id = ? AND active = 1
                GROUP BY track_type
                """,
                (camera_id,)
            )
            
            counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Get recent activity (last 5 minutes)
            recent_ts = int(time.time()) - 300
            cursor = conn.execute(
                """
                SELECT track_type, COUNT(DISTINCT track_key) as count
                FROM scene_tracks
                WHERE camera_id = ? AND last_seen_ts > ?
                GROUP BY track_type
                """,
                (camera_id, recent_ts)
            )
            
            recent_activity = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                "camera_id": camera_id,
                "active_now": counts,
                "recent_activity_5min": recent_activity,
                "total_active": sum(counts.values()),
                "timestamp": int(time.time())
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get scene summary: {str(e)}")


@app.post("/evidence", response_model=ObservationResponse)
async def receive_evidence(request: ObservationRequest):
    """
    Receive observations and evidence from edge device.
    
    Edge devices act as sensors - they observe the world and report facts.
    This endpoint receives those facts and analyzes movement patterns.
    
    The Policy API will:
    1. Analyze object movement (position changes, exits, loitering)
    2. Store the evidence
    3. Classify intent from accumulated evidence (future)
    4. Make decisions about actions to take (future)
    5. Trigger alerts, LLM integration, etc. (future)
    
    The edge device doesn't need to know what the policy decides.
    """
    try:
        with get_db() as conn:
            # Analyze movement for objects with scene_track_keys
            movement_evidence = []
            
            for obj in request.objects:
                track_key = obj.props.get("scene_track_key")
                if not track_key:
                    continue
                
                # Get historical position from scene_tracks
                cursor = conn.execute("""
                    SELECT last_box_json, last_seen_ts, first_seen_ts
                    FROM scene_tracks
                    WHERE camera_id = ? AND track_key = ? AND active = 1
                """, (request.camera_id, track_key))
                
                row = cursor.fetchone()
                if not row:
                    continue
                
                last_box_json, last_seen_ts, first_seen_ts = row
                
                # Parse previous bbox
                if last_box_json:
                    import json
                    try:
                        prev_bbox = json.loads(last_box_json)
                        
                        # Calculate movement distance
                        curr_center_x = (obj.bbox[0] + obj.bbox[2]) / 2
                        curr_center_y = (obj.bbox[1] + obj.bbox[3]) / 2
                        prev_center_x = (prev_bbox[0] + prev_bbox[2]) / 2
                        prev_center_y = (prev_bbox[1] + prev_bbox[3]) / 2
                        
                        dx = curr_center_x - prev_center_x
                        dy = curr_center_y - prev_center_y
                        distance = (dx**2 + dy**2)**0.5
                        
                        # Significant movement threshold (e.g., 50 pixels)
                        if distance > 50:
                            movement_evidence.append({
                                "source": "movement",
                                "feature": "position_changed",
                                "value": f"{distance:.1f}px",
                                "conf": 1.0,
                                "object_id": obj.object_id
                            })
                        
                        # Check for loitering (object stationary for extended time)
                        time_in_scene = request.timestamp - first_seen_ts
                        if distance < 20 and time_in_scene > 30:  # < 20px movement, > 30 seconds
                            movement_evidence.append({
                                "source": "movement",
                                "feature": "loitering",
                                "value": f"{time_in_scene}s",
                                "conf": 1.0,
                                "object_id": obj.object_id
                            })
                            
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
            
            # Check for objects that left (in scene_tracks but not in current observations)
            # Get all active tracks for this camera
            cursor = conn.execute("""
                SELECT track_key, track_type, id
                FROM scene_tracks
                WHERE camera_id = ? AND active = 1
            """, (request.camera_id,))
            
            active_tracks = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
            
            # Get track_keys from current observations
            current_track_keys = {obj.props.get("scene_track_key") for obj in request.objects if obj.props.get("scene_track_key")}
            
            # Find tracks that are no longer present
            missing_track_keys = set(active_tracks.keys()) - current_track_keys
            
            for track_key in missing_track_keys:
                track_type, track_id = active_tracks[track_key]
                
                # Generate exit evidence
                movement_evidence.append({
                    "source": "movement",
                    "feature": f"{track_type}_exited",
                    "value": track_key,
                    "conf": 1.0,
                    "object_id": None
                })
                
                # Mark track as inactive in database
                conn.execute("""
                    UPDATE scene_tracks
                    SET active = 0, last_seen_ts = ?
                    WHERE id = ?
                """, (request.timestamp, track_id))
            
            # Log all evidence (original + movement)
            all_evidence_count = len(request.evidence) + len(movement_evidence)
            
            print(f"[EVIDENCE] Received from camera {request.camera_id}, event {request.event_id}")
            print(f"  Objects: {len(request.objects)}")
            print(f"  Evidence: {len(request.evidence)} original + {len(movement_evidence)} movement")
            if request.transcript:
                print(f"  Transcript: {request.transcript}")
            
            # Log evidence items
            for ev in request.evidence:
                print(f"    - {ev.source}.{ev.feature} = {ev.value} (conf={ev.conf:.2f})")
            
            # Log movement evidence
            for ev in movement_evidence:
                print(f"    - {ev['source']}.{ev['feature']} = {ev['value']} (conf={ev['conf']:.2f})")
            
            return ObservationResponse(
                event_id=request.event_id,
                message=f"Logged {all_evidence_count} evidence items ({len(movement_evidence)} movement) from camera {request.camera_id}"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log evidence: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or default to 8000
    port = int(os.getenv("POLICY_API_PORT", "8000"))
    host = os.getenv("POLICY_API_HOST", "0.0.0.0")
    
    print(f"Starting EchoBell Policy API on {host}:{port}")
    print(f"Database: {DB_PATH}")
    
    uvicorn.run(app, host=host, port=port)
