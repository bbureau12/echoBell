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
from packages.scene.movement_analyzer import MovementAnalyzer, MovementConfig, build_observed_objects
from packages.common.types import VisionResult, SceneObject, Evidence
from packages.common.config_models import RetentionSettings

# Import service layer (DRY business logic)
sys.path.insert(0, os.path.dirname(__file__))
import services

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

# Load movement detection configuration
import json
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
movement_config = MovementConfig()  # Default values
if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, 'r') as f:
            config_data = json.load(f)
            if 'movement_detection' in config_data:
                md_config = config_data['movement_detection']
                movement_config = MovementConfig(
                    significant_movement_px=md_config.get('significant_movement_px', 50.0),
                    loitering_movement_px=md_config.get('loitering_movement_px', 20.0),
                    loitering_time_s=md_config.get('loitering_time_s', 30)
                )
                print(f"[info] Movement detection config loaded: movement={movement_config.significant_movement_px}px, loitering={movement_config.loitering_movement_px}px/{movement_config.loitering_time_s}s")
    except Exception as e:
        print(f"[warning] Failed to load movement config from {CONFIG_PATH}: {e}")

# Initialize SceneTracker (stateful, persists across requests)
scene_tracker = SceneTracker(
    iou_match_threshold=0.30,
    grace_period_s=retention.scene_tracking_grace_period_s
)

# Initialize MovementAnalyzer
movement_analyzer = MovementAnalyzer(movement_config)

# Database connection context manager
@contextmanager
def get_db():
    """Get database connection with proper cleanup."""
    conn = sqlite3.connect(DB_PATH)
    try:
        # Ensure schema exists
        scene_tracker.ensure_schema(conn)
        # Ensure scheduled_event table exists
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER NOT NULL,
                policy_hint TEXT,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            )
        ''')
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
    3. Evaluate policies against evidence
    4. Execute matched policy actions (telegram, speak, webhook, etc.)
    5. Return results
    
    The edge device doesn't need to know what the policy decides.
    """
    try:
        with get_db() as conn:
            # Convert API objects to business layer format
            observed_objects = build_observed_objects(request.objects)
            
            # Analyze movement patterns using business layer
            movement_evidence = movement_analyzer.analyze_movement(
                conn=conn,
                camera_id=request.camera_id,
                current_objects=observed_objects,
                timestamp=request.timestamp
            )
            
            # Detect objects that have exited the scene
            current_track_keys = {
                obj.scene_track_key 
                for obj in observed_objects 
                if obj.scene_track_key
            }
            exit_evidence, inactive_track_ids = movement_analyzer.detect_exits(
                conn=conn,
                camera_id=request.camera_id,
                current_track_keys=current_track_keys,
                timestamp=request.timestamp
            )
            
            # Mark exited tracks as inactive
            movement_analyzer.mark_tracks_inactive(
                conn=conn,
                track_ids=inactive_track_ids,
                timestamp=request.timestamp
            )
            
            # Combine all movement evidence
            all_movement_evidence = movement_evidence + exit_evidence
            # Combine all movement evidence
            all_movement_evidence = movement_evidence + exit_evidence
            
            # Log all evidence (original + movement)
            all_evidence_count = len(request.evidence) + len(all_movement_evidence)
            
            print(f"[EVIDENCE] Received from camera {request.camera_id}, event {request.event_id}")
            print(f"  Objects: {len(request.objects)}")
            print(f"  Evidence: {len(request.evidence)} original + {len(all_movement_evidence)} movement")
            if request.transcript:
                print(f"  Transcript: {request.transcript}")
            
            # Log evidence items
            for ev in request.evidence:
                print(f"    - {ev.source}.{ev.feature} = {ev.value} (conf={ev.conf:.2f})")
            
            # Log movement evidence
            for ev in all_movement_evidence:
                print(f"    - {ev['source']}.{ev['feature']} = {ev['value']} (conf={ev['conf']:.2f})")
            
            # Evaluate policies against evidence
            policy_results = []
            try:
                from packages.policy.apply import evaluate_policies
                
                # Combine all evidence (convert movement evidence to Evidence objects)
                all_evidence = [
                    {
                        'source': ev.source,
                        'feature': ev.feature,
                        'value': ev.value,
                        'conf': ev.conf
                    }
                    for ev in request.evidence
                ]
                all_evidence.extend(all_movement_evidence)
                
                # Build context for policy evaluation
                context = {
                    'camera_id': request.camera_id,
                    'event_id': request.event_id,
                    'timestamp': request.timestamp
                }
                
                # Add track context if available
                if request.objects:
                    first_obj = request.objects[0]
                    track_key = first_obj.props.get('scene_track_key')
                    if track_key:
                        context['track_key'] = track_key
                        context['track_type'] = first_obj.cls  # 'vehicle' or 'person'
                        
                        # Get track duration
                        cursor = conn.execute("""
                            SELECT first_seen_ts FROM scene_tracks
                            WHERE camera_id = ? AND track_key = ?
                        """, (request.camera_id, track_key))
                        row = cursor.fetchone()
                        if row:
                            context['track_duration_seconds'] = request.timestamp - row[0]
                
                # Evaluate policies
                policy_results = await evaluate_policies(
                    evidence=all_evidence,
                    context=context,
                    conn=conn
                )
                
                if policy_results:
                    print(f"  [POLICY] Executed {len(policy_results)} actions:")
                    for result in policy_results:
                        status = "✓" if result.get('success') else "✗"
                        print(f"    {status} {result.get('action_type')} - {result.get('policy_name', 'unknown')}")
                
            except Exception as e:
                print(f"  [POLICY] Policy evaluation failed: {e}")
                import traceback
                traceback.print_exc()
            
            return ObservationResponse(
                event_id=request.event_id,
                message=f"Logged {all_evidence_count} evidence items, executed {len(policy_results)} policy actions"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log evidence: {str(e)}")


# ============================================================================
# Scheduled Event Endpoints (using service layer)
# ============================================================================

class ScheduledEventCreate(BaseModel):
    name: str = Field(..., description="Event name", example="Halloween")
    description: Optional[str] = Field("", description="Event description")
    start_ts: int = Field(..., description="Start time (Unix timestamp)")
    end_ts: int = Field(..., description="End time (Unix timestamp)")
    policy_hint: Optional[str] = Field("", description="Optional policy hint (e.g. 'greet_visitors')")


class ScheduledEventUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    policy_hint: Optional[str] = None


class ScheduledEventResponse(BaseModel):
    id: int
    name: str
    description: str
    start_ts: int
    end_ts: int
    policy_hint: Optional[str]
    created_ts: int
    updated_ts: int


@app.get("/scheduled_events", response_model=list[ScheduledEventResponse])
async def list_scheduled_events():
    """List all scheduled events (sorted by start time)."""
    try:
        with get_db() as conn:
            events = services.list_scheduled_events(conn)
            return [ScheduledEventResponse(**event) for event in events]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list scheduled events: {str(e)}")


@app.post("/scheduled_events", response_model=ScheduledEventResponse, status_code=201)
async def create_scheduled_event(event: ScheduledEventCreate):
    """Create a new scheduled event."""
    try:
        with get_db() as conn:
            created = services.create_scheduled_event(
                conn=conn,
                name=event.name,
                start_ts=event.start_ts,
                end_ts=event.end_ts,
                description=event.description or "",
                policy_hint=event.policy_hint or ""
            )
            return ScheduledEventResponse(**created)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create scheduled event: {str(e)}")


@app.get("/scheduled_events/{event_id}", response_model=ScheduledEventResponse)
async def get_scheduled_event(event_id: int):
    """Get a scheduled event by ID."""
    try:
        with get_db() as conn:
            event = services.get_scheduled_event(conn, event_id)
            if not event:
                raise HTTPException(status_code=404, detail="Scheduled event not found")
            return ScheduledEventResponse(**event)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get scheduled event: {str(e)}")


@app.patch("/scheduled_events/{event_id}", response_model=ScheduledEventResponse)
async def update_scheduled_event(event_id: int, update: ScheduledEventUpdate):
    """Update a scheduled event (partial update)."""
    try:
        with get_db() as conn:
            updated = services.update_scheduled_event(
                conn=conn,
                event_id=event_id,
                name=update.name,
                description=update.description,
                start_ts=update.start_ts,
                end_ts=update.end_ts,
                policy_hint=update.policy_hint
            )
            if not updated:
                raise HTTPException(status_code=404, detail="Scheduled event not found")
            return ScheduledEventResponse(**updated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update scheduled event: {str(e)}")


@app.delete("/scheduled_events/{event_id}", status_code=204)
async def delete_scheduled_event(event_id: int):
    """Delete a scheduled event by ID."""
    try:
        with get_db() as conn:
            deleted = services.delete_scheduled_event(conn, event_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Scheduled event not found")
            return
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete scheduled event: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or default to 8000
    port = int(os.getenv("POLICY_API_PORT", "8000"))
    host = os.getenv("POLICY_API_HOST", "0.0.0.0")
    
    print(f"Starting EchoBell Policy API on {host}:{port}")
    print(f"Database: {DB_PATH}")
    
    uvicorn.run(app, host=host, port=port)

