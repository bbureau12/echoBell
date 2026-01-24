import time
import sys
import os
import yaml
import requests
from typing import Optional

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from packages.perception.vision import snapshot_and_detect
from packages.perception.asr import transcribe
from packages.classify.classify_and_log import classify_and_log
from packages.policy.loader import load_policies
from packages.policy.apply import choose_action
from packages.tts.piper import speak
from packages.common.types import Evidence
from storage.store import log_event

# Get absolute paths for data files
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB = os.path.join(PROJECT_ROOT, "data", "doorbell.db")
RTSP = os.path.join(PROJECT_ROOT, "data", "sherriff.jpg")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# Load configuration
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

MODE = config['agent']['mode']
CAMERA_ID = config['agent']['camera_id']
POLICY_API_URL = config['policy_api']['base_url']
API_TIMEOUT = config['policy_api']['timeout']

def call_policy_api_for_scene_update(vision, event_id: str, camera_id: int, timestamp: int) -> tuple[list[Evidence], dict]:
    """
    Call Policy API to update scene tracking.
    
    Returns:
        (scene_evidence, track_keys) - Evidence from scene tracking and object_id -> track_key mapping
    """
    try:
        # Extract plate HMACs from vision objects
        plate_hmac_by_object_id = {}
        for obj in vision.objects or []:
            if obj.object_id is not None and "plate_hmac" in obj.props:
                plate_hmac_by_object_id[str(obj.object_id)] = obj.props["plate_hmac"]
        
        # Build request payload
        detections = []
        for obj in vision.objects or []:
            if obj.object_id is not None:
                detections.append({
                    "object_id": obj.object_id,
                    "cls": obj.cls,
                    "raw_class": obj.props.get("raw_class"),
                    "conf": obj.conf,
                    "bbox": {
                        "x": obj.bbox[0],
                        "y": obj.bbox[1],
                        "w": obj.bbox[2],
                        "h": obj.bbox[3]
                    },
                    "props": obj.props
                })
        
        payload = {
            "camera_id": camera_id,
            "timestamp": timestamp,
            "event_id": event_id,
            "detections": detections,
            "plate_hmac_by_object_id": plate_hmac_by_object_id
        }
        
        # Call Policy API
        response = requests.post(
            f"{POLICY_API_URL}/scene/update",
            json=payload,
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        
        result = response.json()
        
        # Convert scene evidence back to Evidence objects
        scene_evidence = [
            Evidence(
                source=ev["source"],
                feature=ev["feature"],
                value=ev["value"],
                conf=ev["conf"],
                object_id=ev.get("object_id")
            )
            for ev in result["scene_evidence"]
        ]
        
        # Get track keys
        track_keys = result.get("track_keys", {})
        # Convert string keys back to int
        track_keys = {int(k): v for k, v in track_keys.items()}
        
        print(f"[POLICY API] {result['message']}")
        return scene_evidence, track_keys
        
    except requests.RequestException as e:
        print(f"[POLICY API] WARNING: Failed to contact Policy API: {e}")
        if config['fallback']['warn_only']:
            print("[POLICY API] Continuing without scene tracking...")
            return [], {}
        else:
            raise


def send_evidence_to_policy_api(vision, event_id: str, camera_id: int, timestamp: int, transcript: str = None):
    """
    Send observations and evidence to Policy API.
    
    Edge device acts as a sensor - reports what it sees/hears without making decisions.
    The Policy API will classify intent and make policy decisions.
    
    Args:
        vision: VisionResult with objects and evidence
        event_id: Unique event identifier
        camera_id: Camera/edge device identifier
        timestamp: Unix timestamp in seconds
        transcript: Optional audio transcript
    """
    try:
        # Build objects payload
        objects = []
        for obj in vision.objects or []:
            if obj.object_id is not None:
                objects.append({
                    "object_id": obj.object_id,
                    "label": obj.label,
                    "bbox": list(obj.box) if obj.box else [0, 0, 0, 0],
                    "props": obj.props or {}
                })
        
        # Build evidence payload
        evidence = []
        for ev in vision.evidence or []:
            evidence.append({
                "source": ev.source,
                "feature": ev.feature,
                "value": ev.value,
                "conf": ev.conf,
                "object_id": ev.object_id
            })
        
        # Build request payload
        payload = {
            "camera_id": camera_id,
            "event_id": event_id,
            "timestamp": timestamp,
            "objects": objects,
            "evidence": evidence,
            "context": {
                "mode": MODE,
                "person_present": vision.person_present,
                "vehicle_present": vision.vehicle_present,
                "package_box": vision.package_box
            }
        }
        
        # Add transcript if available
        if transcript:
            payload["transcript"] = transcript
        
        # Call Policy API
        response = requests.post(
            f"{POLICY_API_URL}/evidence",
            json=payload,
            timeout=API_TIMEOUT
        )
        response.raise_for_status()
        
        result = response.json()
        print(f"[POLICY API] Evidence sent: {result['message']}")
        return True
        
    except requests.RequestException as e:
        print(f"[POLICY API] WARNING: Failed to send evidence to Policy API: {e}")
        if config['fallback']['warn_only']:
            print("[POLICY API] Continuing without policy decisions...")
            return False
        else:
            raise


def handle_ring():
    import sqlite3
    conn = sqlite3.connect(DB)
    
    policies = load_policies()
    
    # OBSERVE - get vision data
    vision = snapshot_and_detect(DB, RTSP)
    
    # Generate event ID for this ring
    event_id = f"evt_{int(time.time())}_{CAMERA_ID}"
    
    # SCENE TRACKING - Call Policy API
    scene_evidence, track_keys = call_policy_api_for_scene_update(
        vision=vision,
        event_id=event_id,
        camera_id=CAMERA_ID,
        timestamp=int(time.time())
    )
    
    # Add scene evidence to vision result
    vision.evidence.extend(scene_evidence)
    
    # Set scene_track_key on vision objects (for linkage to use)
    if vision.objects and track_keys:
        for obj in vision.objects:
            if obj.object_id is not None and obj.object_id in track_keys:
                obj.props["scene_track_key"] = track_keys[obj.object_id]
    
    # CLASSIFY & LOG - without scene tracker (API already handled it)
    # This will:
    # - Classify intent from vision + scene evidence
    # - Link people to vehicles (using scene_track_key)
    # - Log visitor event
    classified, event_id = classify_and_log(
        conn=conn,
        vision=vision,
        transcript=None,  # Will get transcript below
        camera_id=CAMERA_ID,
        mode=MODE,
        scene_tracker=None,  # Scene tracking now handled by Policy API
    )
    
    # Log the initial motion event
    log_event(DB, etype="motion", mode=MODE, snapshot=vision.snapshot_path)

    # GREET
    greet = "Hi, I’m Echo-Bell. I keep an eye on things here.  How can I help?"
    speak(greet)

    # LISTEN
    asr = transcribe(seconds=4)

    # UPDATE with transcript - classify_and_log already handled intent classification
    # Just update the event with the transcript if we got one
    if asr.text:
        conn.execute(
            "UPDATE visitor_events SET transcript = ? WHERE event_id = ?",
            (asr.text, event_id)
        )
        conn.commit()
    
    # SEND EVIDENCE TO POLICY API
    # Now that we have complete observations (vision + scene + audio), send to policy layer
    # Policy API will make decisions about what to do with this information
    send_evidence_to_policy_api(
        vision=vision,
        event_id=event_id,
        camera_id=CAMERA_ID,
        timestamp=int(time.time()),
        transcript=asr.text if asr.text else None
    )

    # DECIDE - use the classified intent from classify_and_log
    ctx = {"intent": classified.intent, "mode": MODE, "vision": vision}
    plan = choose_action(policies, ctx)

    # ACT
    if msg := plan.get("speak"):
        speak(msg)

    # LOG - use the classified data
    log_event(DB, etype="speak", intent=classified.intent, confidence=classified.conf, 
              urgency=classified.urgency, mode=MODE, snapshot=vision.snapshot_path, 
              transcript=asr.text, actions=plan)
    
    conn.close()

if __name__ == "__main__":
    print("Echo-Bell pre-LLM agent ready. Simulating a ring in 2s…")
    time.sleep(2)
    handle_ring()
