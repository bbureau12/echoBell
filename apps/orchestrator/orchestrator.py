import threading
import sys
import os
import time

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

# Import Event class and EventBus
sys.path.append(os.path.dirname(__file__))
import event
from event import Event

# Import EventBus using importlib to handle the hyphenated filename
import importlib.util
event_bus_path = os.path.join(os.path.dirname(__file__), "event-bus.py")
spec = importlib.util.spec_from_file_location("event_bus", event_bus_path)
event_bus_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(event_bus_module)
EventBus = event_bus_module.EventBus

# Import handle_ring from the doorbell-agent directory
import importlib.util
doorbell_orchestrator_path = os.path.join(project_root, 'apps', 'doorbell-agent', 'orchestrator.py')
spec = importlib.util.spec_from_file_location("doorbell_orchestrator", doorbell_orchestrator_path)
doorbell_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doorbell_module)
handle_ring = doorbell_module.handle_ring

# Import vision detection for driveway monitoring
from packages.perception.vision import snapshot_and_detect

# Import camera loop from camera-agent
camera_loop_path = os.path.join(project_root, 'apps', 'camera-agent', 'loop.py')
spec = importlib.util.spec_from_file_location("camera_loop_module", camera_loop_path)
camera_loop_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera_loop_module)
driveway_loop = camera_loop_module.driveway_loop


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
        target=driveway_loop,
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
