"""
Camera Loop - Passive Monitoring

Continuously monitors camera feed and sends detections to policy server.
Used for passive cameras (driveway, backyard, etc.)
"""

import os
import time
import sys
from queue import Queue
from typing import Optional

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from packages.perception.vision import snapshot_and_detect


def camera_loop(
    rtsp: str,
    event_queue: Queue,
    camera_id: int = 1,
    poll_sec: float = 1.0,
    persistence_threshold: float = 3.0,
    db_path: Optional[str] = None
):
    """
    Passive camera monitoring loop.
    
    Polls camera at regular intervals and queues detection events when:
    - Person or vehicle detected
    - Object has been in frame for persistence_threshold seconds
    
    Args:
        rtsp: RTSP URL or image path
        event_queue: Queue to publish detection events
        camera_id: Camera identifier
        poll_sec: Polling interval in seconds
        persistence_threshold: Seconds object must persist before alerting
        db_path: Optional database path for vision detection
    """
    seen_since = None
    last_present = False
    
    print(f"[CAMERA {camera_id}] Starting passive monitoring loop...")
    print(f"[CAMERA {camera_id}] Polling every {poll_sec}s, threshold {persistence_threshold}s")

    while True:
        try:
            # Run vision detection
            vision = snapshot_and_detect(rtsp, db_path=db_path, debug=False)

            # Check if person or vehicle present
            moving_thing = vision.person_present or vision.vehicle_present
            now = time.time()

            if moving_thing:
                # Object detected
                if not last_present:
                    # First detection - start persistence timer
                    seen_since = now
                    print(f"[CAMERA {camera_id}] Detection started...")
                    
                last_present = True

                # Check if object has persisted long enough
                if now - seen_since > persistence_threshold:
                    kind = "person" if vision.person_present else "vehicle"
                    
                    # Queue detection event
                    event = {
                        "source": f"camera_{camera_id}",
                        "type": "detection",
                        "kind": kind,
                        "camera_id": camera_id,
                        "timestamp": int(now),
                        "snapshot": vision.snapshot_path,
                        "vision": vision,
                        "person_present": vision.person_present,
                        "vehicle_present": vision.vehicle_present,
                    }
                    
                    event_queue.put(event)
                    print(f"[CAMERA {camera_id}] {kind.upper()} detected (snapshot: {vision.snapshot_path})")
                    
                    # Debounce - don't alert again for a few seconds
                    seen_since = now + 5.0
            else:
                # No detection - reset state
                last_present = False
                seen_since = None

            time.sleep(poll_sec)
            
        except KeyboardInterrupt:
            print(f"\n[CAMERA {camera_id}] Shutting down...")
            break
        except Exception as e:
            print(f"[CAMERA {camera_id}] ERROR: {e}")
            time.sleep(poll_sec)  # Continue even on error
