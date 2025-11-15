import threading
import sys
import os
import time

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

# Import Event class directly (avoid relative import issues when running as script)
sys.path.append(os.path.dirname(__file__))
import event
Event = event.Event

# Import handle_ring from the doorbell-agent directory
import importlib.util
doorbell_orchestrator_path = os.path.join(project_root, 'apps', 'doorbell-agent', 'orchestrator.py')
spec = importlib.util.spec_from_file_location("doorbell_orchestrator", doorbell_orchestrator_path)
doorbell_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doorbell_module)
handle_ring = doorbell_module.handle_ring

# Import vision detection for driveway monitoring
from packages.perception.vision import snapshot_and_detect

# Create camera loop function (adapted from camera-agent/loop.py)
def camera_loop(rtsp: str, bus, poll_sec: float = 1.0):
    """Monitor driveway for approaching vehicles/people"""
    seen_since = None
    last_present = False
    
    # Use test image if RTSP fails
    test_image = os.path.join(project_root, "data", "sherriff.jpg")

    while True:
        try:
            # Use a default database path for vision
            db_path = os.path.join(project_root, "data", "doorbell.db")
            
            # Try RTSP first, fall back to test image
            try:
                vision = snapshot_and_detect(db_path, rtsp, debug=False)
            except RuntimeError:
                # RTSP failed, use test image instead
                vision = snapshot_and_detect(db_path, test_image, debug=False)

            moving_thing = vision.person_present or vision.vehicle_present
            now = time.time()

            if moving_thing:
                if not last_present:
                    seen_since = now
                last_present = True

                if now - seen_since > 3.0:  # in frame for >3s
                    kind = "person" if vision.person_present else "vehicle"
                    event = Event(
                        source="driveway",
                        type="approach",
                        kind=kind,
                        snapshot=vision.snapshot_path
                    )
                    bus.publish(event)
                    print(f"[Camera] {kind} detected approaching")
                    # debounce a bit
                    seen_since = now + 5.0
            else:
                last_present = False
                seen_since = None

        except Exception as e:
            print(f"[Camera] Error in camera loop: {e}")

        time.sleep(poll_sec)

# Simple EventBus implementation since event-bus.py might have issues
class EventBus:
    def __init__(self):
        self.events = []
        
    def publish(self, event):
        self.events.append(event)
        
    def subscribe(self):
        while not self.events:
            time.sleep(0.1)  # Simple polling
        return self.events.pop(0)

# Simplified doorbell simulation
def simulate_doorbell(bus):
    time.sleep(5)  # Wait 5 seconds
    event = Event(source="doorbell", type="ring")
    bus.publish(event)
    print("[Doorbell] Ring event published")

def bell_orchestrator():
    bus = EventBus()

    # Start Camera 1 thread
    threading.Thread(
        target=camera_loop,
        args=("rtsp://driveway", bus),
        daemon=True
    ).start()

    # Start doorbell thread
    threading.Thread(
        target=simulate_doorbell, 
        args=(bus,), 
        daemon=True
    ).start()

    print("[Bell] Listening for events...")

    while True:
        evt: Event = bus.subscribe()

        if evt.type == "shutdown":
            print("[Bell] Shutting down.")
            break

        if evt.source == "driveway" and evt.type == "approach":
            print(f"[Bell] Approach → {evt.kind} ({evt.snapshot})")
            # Optional: speak/alert

        if evt.source == "doorbell" and evt.type == "ring":
            print("[Bell] Doorbell ring received.")
            handle_ring()  # Call the actual doorbell handler

if __name__ == "__main__":
    bell_orchestrator()
