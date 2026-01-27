"""
Button Loop - Interactive Doorbell

Waits for doorbell button press, then performs:
1. Vision detection
2. Audio greeting (TTS)
3. Listen for response (ASR)
4. Send to policy server
5. Execute policy actions

Used for interactive doorbells.
"""

import time
import sys
import os
from queue import Queue
from typing import Optional

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from packages.perception.vision import snapshot_and_detect
from packages.perception.asr import transcribe
from packages.tts.piper import speak
from storage.store import log_event


def handle_button_press(
    rtsp: str,
    event_queue: Queue,
    camera_id: int = 1,
    db_path: str = "data/doorbell.db",
    mode: str = "WORKING",
    greet_message: str = "Hi, I'm Echo-Bell. I keep an eye on things here. How can I help?"
):
    """
    Handle a single doorbell button press.
    
    Performs the full interactive flow:
    - Detect who's there
    - Greet visitor
    - Listen to their response
    - Queue event for policy processing
    
    Args:
        rtsp: RTSP URL or image path
        event_queue: Queue to publish button events
        camera_id: Camera identifier
        db_path: Database path
        mode: Operating mode (WORKING, AWAY, etc.)
        greet_message: TTS greeting message
    """
    print(f"[DOORBELL {camera_id}] Button pressed!")
    
    # OBSERVE - get vision data
    vision = snapshot_and_detect(rtsp, db_path=db_path, debug=False)
    
    # Log initial detection
    log_event(db_path, etype="motion", mode=mode, snapshot=vision.snapshot_path)
    
    # GREET
    print(f"[DOORBELL {camera_id}] Speaking: {greet_message}")
    speak(greet_message)
    
    # LISTEN
    print(f"[DOORBELL {camera_id}] Listening...")
    asr = transcribe(seconds=4)
    transcript = asr.text if asr.text else None
    
    if transcript:
        print(f"[DOORBELL {camera_id}] Heard: {transcript}")
    else:
        print(f"[DOORBELL {camera_id}] No speech detected")
    
    # Queue button event for policy processing
    event = {
        "source": f"doorbell_{camera_id}",
        "type": "button_press",
        "kind": "interactive",
        "camera_id": camera_id,
        "timestamp": int(time.time()),
        "snapshot": vision.snapshot_path,
        "vision": vision,
        "transcript": transcript,
        "person_present": vision.person_present,
        "vehicle_present": vision.vehicle_present,
    }
    
    event_queue.put(event)
    print(f"[DOORBELL {camera_id}] Event queued for policy processing")


def button_loop(
    rtsp: str,
    event_queue: Queue,
    camera_id: int = 1,
    db_path: str = "data/doorbell.db",
    mode: str = "WORKING",
    simulate: bool = True,
    simulate_interval: float = 30.0
):
    """
    Wait for doorbell button presses and handle them.
    
    In production, this would monitor GPIO or other button interface.
    In development/testing, simulates button presses at regular intervals.
    
    Args:
        rtsp: RTSP URL or image path
        event_queue: Queue to publish button events
        camera_id: Camera identifier
        db_path: Database path
        mode: Operating mode
        simulate: If True, simulate button presses for testing
        simulate_interval: Seconds between simulated button presses
    """
    print(f"[DOORBELL {camera_id}] Starting button listener...")
    
    if simulate:
        print(f"[DOORBELL {camera_id}] SIMULATION MODE - pressing button every {simulate_interval}s")
    
    while True:
        try:
            if simulate:
                # Simulate button press for testing
                time.sleep(simulate_interval)
                print(f"\n[DOORBELL {camera_id}] === SIMULATED BUTTON PRESS ===")
                
            else:
                # TODO: Real GPIO button monitoring
                # For now, just wait
                time.sleep(0.1)
                continue
            
            # Handle the button press
            handle_button_press(
                rtsp=rtsp,
                event_queue=event_queue,
                camera_id=camera_id,
                db_path=db_path,
                mode=mode
            )
            
        except KeyboardInterrupt:
            print(f"\n[DOORBELL {camera_id}] Shutting down...")
            break
        except Exception as e:
            print(f"[DOORBELL {camera_id}] ERROR: {e}")
            time.sleep(1)  # Brief pause before continuing
