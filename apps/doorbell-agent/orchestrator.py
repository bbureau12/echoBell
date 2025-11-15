import time
import sys
import os

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from packages.perception.vision import snapshot_and_detect
from packages.perception.asr import transcribe
from packages.classify.intent import classify
from packages.policy.loader import load_policies
from packages.policy.apply import choose_action
from packages.tts.piper import speak
from storage.store import log_event

# Get absolute paths for data files
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB = os.path.join(PROJECT_ROOT, "data", "doorbell.db")
RTSP = os.path.join(PROJECT_ROOT, "data", "sherriff.jpg")
MODE = "WORKING"  # later: read from DB

def handle_ring():
    policies = load_policies()
    # OBSERVE
    vision = snapshot_and_detect(DB, RTSP)
    log_event(DB, etype="motion", mode=MODE, snapshot=vision.snapshot_path)

    # GREET
    greet = "Hi, I’m Echo-Bell. I keep an eye on things here.  How can I help?"
    speak(greet)

    # LISTEN
    asr = transcribe(seconds=4)

    # INTERPRET
    cls = classify(asr.text, vision)

    # DECIDE
    ctx = {"intent": cls.intent, "mode": MODE, "vision": vision}
    plan = choose_action(policies, ctx)

    # ACT
    if msg := plan.get("speak"):
        speak(msg)

    # LOG
    log_event(DB, etype="speak", intent=cls.intent, confidence=cls.conf, urgency=cls.urgency,
              mode=MODE, snapshot=vision.snapshot_path, transcript=asr.text, actions=plan)

if __name__ == "__main__":
    print("Echo-Bell pre-LLM agent ready. Simulating a ring in 2s…")
    time.sleep(2)
    handle_ring()
