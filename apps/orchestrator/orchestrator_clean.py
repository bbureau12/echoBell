import threading
import sys
import os
import time
from queue import Queue

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

# Import Event class
from .event import Event

# Import handle_ring from the doorbell-agent directory
sys.path.append(os.path.join(project_root, 'apps', 'doorbell-agent'))
from orchestrator import handle_ring

class EventBus:
    def __init__(self):
        self.queue = Queue()

    def publish(self, event):
        """Thread-safe publish."""
        self.queue.put(event)

    def subscribe(self):
        """Block until an event is available and return it."""
        return self.queue.get()

    def shutdown(self):
        """Tell listeners to stop."""
        self.publish(Event(source="system", type="shutdown"))

def simulate_doorbell(bus):
    """Simulate a doorbell ring after 5 seconds"""
    time.sleep(5)
    event = Event(source="doorbell", type="ring")
    bus.publish(event)
    print("[Doorbell] Ring event published")

def bell_orchestrator():
    bus = EventBus()

    # Start doorbell thread
    threading.Thread(
        target=simulate_doorbell, 
        args=(bus,), 
        daemon=True
    ).start()

    print("[Bell] Listening for events...")

    while True:
        evt = bus.subscribe()

        if evt.type == "shutdown":
            print("[Bell] Shutting down.")
            break

        if evt.source == "doorbell" and evt.type == "ring":
            print("[Bell] Doorbell ring received.")
            handle_ring()  # Call the actual doorbell handler

if __name__ == "__main__":
    bell_orchestrator()