import os
import time
from queue import Queue
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
from packages.perception.vision import snapshot_and_detect

def driveway_loop(rtsp: str, bus: Queue, poll_sec: float = 1.0):
    seen_since = None
    last_present = False

    while True:
        vision = snapshot_and_detect(rtsp, debug=False)

        moving_thing = vision.person_present or vision.vehicle_present
        now = time.time()

        if moving_thing:
            if not last_present:
                seen_since = now
            last_present = True

            if now - seen_since > 3.0:  # in frame for >3s
                kind = "person" if vision.person_present else "vehicle"
                bus.put({
                    "source": "driveway",
                    "type": "approach",
                    "kind": kind,
                    "snapshot": vision.snapshot_path,
                })
                # debounce a bit
                seen_since = now + 5.0
        else:
            last_present = False
            seen_since = None

        time.sleep(poll_sec)