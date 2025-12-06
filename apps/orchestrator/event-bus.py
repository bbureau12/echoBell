from queue import Queue
from event import Event

class EventBus:
    def __init__(self):
        self.queue = Queue()

    def publish(self, event: Event):
        """Thread-safe publish."""
        self.queue.put(event)

    def subscribe(self):
        """Block until an event is available and return it."""
        return self.queue.get()

    def shutdown(self):
        """Tell listeners to stop."""
        self.publish(Event(source="system", type="shutdown"))
