import time
import sys
import os

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from packages.perception.vision import snapshot_and_detect
from packages.perception.asr import transcribe
from packages.classify.classify_and_log import classify_and_log
from packages.policy.loader import load_policies
from packages.policy.apply import choose_action
from packages.tts.piper import speak
from packages.scene.scene_tracker import SceneTracker
from packages.common.config_models import RetentionSettings
from storage.store import log_event

# Get absolute paths for data files
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB = os.path.join(PROJECT_ROOT, "data", "doorbell.db")
RTSP = os.path.join(PROJECT_ROOT, "data", "sherriff.jpg")
MODE = "WORKING"  # later: read from DB

# Initialize retention settings
retention = RetentionSettings()

# Initialize scene tracker for temporal awareness
scene_tracker = SceneTracker(
    iou_match_threshold=0.30,
    grace_period_s=retention.scene_tracking_grace_period_s
)

def handle_ring():
    import sqlite3
    conn = sqlite3.connect(DB)
    
    # Ensure scene tracker schema exists
    scene_tracker.ensure_schema(conn)
    
    policies = load_policies()
    
    # OBSERVE - get vision data
    vision = snapshot_and_detect(DB, RTSP)
    
    # CLASSIFY & LOG - with scene awareness
    # This will:
    # - Track vehicles/people entering/exiting
    # - Link people to vehicles they arrived in
    # - Detect license plates and link to vehicles
    # - Generate scene.* evidence (vehicle_entered, person_present, etc.)
    classified, event_id = classify_and_log(
        conn=conn,
        vision=vision,
        transcript=None,  # Will get transcript below
        camera_id=1,
        mode=MODE,
        scene_tracker=scene_tracker,
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
