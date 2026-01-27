#!/usr/bin/env python3
"""
EchoBell Unified Edge Agent

Single agent that can operate as:
- Passive camera (continuous monitoring)
- Interactive doorbell (button-triggered with ASR/TTS)

Configuration in config.yaml determines behavior.
"""

import os
import sys
import argparse
import yaml
import time
import threading
import requests
from queue import Queue
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from edge.agent.camera_loop import camera_loop
from edge.agent.button_loop import button_loop
from edge.agent.image_server import ImageServer
from packages.common.types import Evidence


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def send_to_policy_api(event: dict, config: dict) -> Optional[dict]:
    """
    Send detection event to policy server.
    
    Args:
        event: Detection event from camera_loop or button_loop
        config: Configuration dict
        
    Returns:
        Policy server response or None if failed
    """
    try:
        vision = event['vision']
        
        # Build objects payload
        objects = []
        for obj in vision.objects or []:
            if obj.object_id is not None:
                objects.append({
                    "object_id": obj.object_id,
                    "label": obj.label,
                    "bbox": list(obj.box) if obj.box else [0, 0, 0, 0],
                    "confidence": obj.conf,
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
            "camera_id": event['camera_id'],
            "event_id": f"evt_{event['timestamp']}_{event['camera_id']}",
            "timestamp": event['timestamp'],
            "event_type": event['type'],
            "objects": objects,
            "evidence": evidence,
            "context": {
                "mode": config['agent']['mode'],
                "person_present": event['person_present'],
                "vehicle_present": event['vehicle_present'],
                "source": event['source']
            }
        }
        
        # Add transcript if available (from doorbell)
        if 'transcript' in event and event['transcript']:
            payload["transcript"] = event['transcript']
        
        # Add snapshot URL if image server is enabled
        if config['image_server']['enabled'] and event.get('snapshot'):
            filename = os.path.basename(event['snapshot'])
            snapshot_url = f"http://localhost:{config['image_server']['port']}/{filename}"
            payload["snapshot_url"] = snapshot_url
        
        # Call Policy API
        api_url = config['policy_api']['base_url']
        timeout = config['policy_api']['timeout']
        
        response = requests.post(
            f"{api_url}/observations",
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()
        
        result = response.json()
        print(f"[POLICY_API] {result.get('message', 'OK')}")
        
        return result
        
    except requests.RequestException as e:
        print(f"[POLICY_API] WARNING: Failed to contact policy server: {e}")
        if config['fallback']['warn_only']:
            print("[POLICY_API] Continuing without policy decisions...")
            return None
        else:
            raise


def process_events(event_queue: Queue, config: dict):
    """
    Process events from camera_loop or button_loop.
    
    Sends events to policy server and executes any actions.
    """
    print("[AGENT] Event processor started")
    
    while True:
        try:
            # Get event from queue
            event = event_queue.get()
            
            print(f"\n[AGENT] Processing event: {event['type']} from {event['source']}")
            
            # Send to policy server
            response = send_to_policy_api(event, config)
            
            # Execute actions from policy server
            if response and 'actions' in response:
                for action in response['actions']:
                    execute_action(action, config)
            
        except KeyboardInterrupt:
            print("\n[AGENT] Event processor shutting down...")
            break
        except Exception as e:
            print(f"[AGENT] ERROR processing event: {e}")


def execute_action(action: dict, config: dict):
    """
    Execute an action returned by the policy server.
    
    Args:
        action: Action dict with 'type' and parameters
        config: Configuration dict
    """
    action_type = action.get('type')
    
    if action_type == 'speak':
        # Only execute if device has speaker
        if config['agent']['has_speaker']:
            from packages.tts.piper import speak
            message = action.get('message', '')
            print(f"[ACTION] Speaking: {message}")
            speak(message)
        else:
            print(f"[ACTION] SKIP speak (no speaker): {action.get('message')}")
    
    elif action_type == 'telegram':
        print(f"[ACTION] Telegram notification: {action.get('message')}")
        # Policy server handles Telegram - no action needed on edge
    
    elif action_type == 'log':
        print(f"[ACTION] Log: {action.get('message')}")
    
    else:
        print(f"[ACTION] Unknown action type: {action_type}")


def main():
    """Main entry point for unified edge agent"""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="EchoBell Unified Edge Agent")
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config.yaml (default: ./config.yaml)'
    )
    parser.add_argument(
        '--camera-id',
        type=int,
        default=None,
        help='Override camera_id from config'
    )
    parser.add_argument(
        '--rtsp',
        type=str,
        default=None,
        help='Override rtsp_url from config'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Apply command-line overrides
    if args.camera_id is not None:
        config['agent']['camera_id'] = args.camera_id
    if args.rtsp is not None:
        config['camera']['rtsp_url'] = args.rtsp
    
    # Print configuration
    print("=" * 60)
    print("🔔 EchoBell Unified Edge Agent")
    print("=" * 60)
    print(f"Camera ID: {config['agent']['camera_id']}")
    print(f"Mode: {config['agent']['mode']}")
    print(f"RTSP: {config['camera']['rtsp_url']}")
    print(f"Has Button: {config['agent']['has_button']}")
    print(f"Has Speaker: {config['agent']['has_speaker']}")
    print(f"Has Microphone: {config['agent']['has_microphone']}")
    print(f"Policy Server: {config['policy_api']['base_url']}")
    print("=" * 60 + "\n")
    
    # Create event queue for inter-thread communication
    event_queue = Queue()
    
    # Start HTTP image server if enabled
    image_server = None
    if config['image_server']['enabled']:
        image_server = ImageServer(
            port=config['image_server']['port'],
            directory=config['image_server']['directory']
        )
        image_server.start()
        
        # Start auto-cleanup if enabled
        if config['image_server']['cleanup_enabled']:
            def cleanup_loop():
                while True:
                    time.sleep(3600)  # Run every hour
                    image_server.cleanup_old_images(
                        config['image_server']['cleanup_hours']
                    )
            
            threading.Thread(target=cleanup_loop, daemon=True).start()
            print(f"[IMAGE_SERVER] Auto-cleanup enabled ({config['image_server']['cleanup_hours']}h)\n")
    
    # Start event processor thread
    processor_thread = threading.Thread(
        target=process_events,
        args=(event_queue, config),
        daemon=True
    )
    processor_thread.start()
    
    # Get database path
    db_path = os.path.join(PROJECT_ROOT, config['database']['path'])
    
    # Start appropriate loop based on configuration
    if config['agent']['has_button']:
        # Interactive doorbell mode
        print("[AGENT] Starting in DOORBELL mode (button-triggered)\n")
        button_loop(
            rtsp=config['camera']['rtsp_url'],
            event_queue=event_queue,
            camera_id=config['agent']['camera_id'],
            db_path=db_path,
            mode=config['agent']['mode'],
            simulate=True,  # TODO: Real GPIO
            simulate_interval=30.0
        )
    else:
        # Passive camera mode
        print("[AGENT] Starting in CAMERA mode (continuous monitoring)\n")
        camera_loop(
            rtsp=config['camera']['rtsp_url'],
            event_queue=event_queue,
            camera_id=config['agent']['camera_id'],
            poll_sec=config['camera']['poll_interval'],
            persistence_threshold=config['camera']['persistence_threshold'],
            db_path=db_path
        )


if __name__ == '__main__':
    main()
