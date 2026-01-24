"""
EchoBell Scheduler Daemon

Orchestrates edge camera devices by periodically triggering them to capture
and analyze camera feeds. Maintains camera registry in SQLite and supports
dynamic configuration updates without restart.

Architecture:
- Reads camera registry from SQLite (hot-reloadable)
- Triggers edge cameras via HTTP on schedule
- Tracks failures and disables problematic cameras
- Reports health to Policy API

Usage:
    python scheduler.py
"""

import time
import sqlite3
import yaml
import os
import sys
import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

# Setup logging
logging.basicConfig(
    level=getattr(logging, config['logging']['level']),
    format='%(asctime)s - [SCHEDULER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = os.path.join(PROJECT_ROOT, config['database']['path'])


class CameraRegistry:
    """Manages the registry of edge cameras from SQLite database."""
    
    def __init__(self, db_path: str, refresh_interval_s: int):
        self.db_path = db_path
        self.refresh_interval_s = refresh_interval_s
        self.cameras: List[Dict] = []
        self.last_refresh_ts = 0
        
    def refresh_if_needed(self):
        """Reload camera list from database if refresh interval has passed."""
        now = int(time.time())
        if now - self.last_refresh_ts >= self.refresh_interval_s:
            self.refresh()
            
    def refresh(self):
        """Force reload camera list from database."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT camera_id, name, endpoint_url, enabled, capture_interval_s,
                       last_capture_ts, last_success_ts, consecutive_failures, metadata
                FROM edge_cameras
                WHERE enabled = 1
                ORDER BY camera_id
            """)
            
            self.cameras = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            self.last_refresh_ts = int(time.time())
            logger.info(f"Refreshed camera registry: {len(self.cameras)} active cameras")
            
        except Exception as e:
            logger.error(f"Failed to refresh camera registry: {e}")
            
    def get_cameras_needing_capture(self, now_ts: int) -> List[Dict]:
        """Get cameras that are due for capture based on their intervals."""
        cameras_due = []
        
        for camera in self.cameras:
            # Skip if too many consecutive failures
            max_failures = config['scheduler'].get('max_consecutive_failures', 5)
            if camera['consecutive_failures'] >= max_failures:
                continue
            
            # Determine interval (per-camera or default)
            interval = camera['capture_interval_s'] or config['scheduler']['default_capture_interval_s']
            
            # Check if due for capture
            last_capture = camera['last_capture_ts'] or 0
            if now_ts - last_capture >= interval:
                cameras_due.append(camera)
                
        return cameras_due
    
    def update_capture_status(self, camera_id: int, success: bool):
        """Update camera capture status in database."""
        try:
            conn = sqlite3.connect(self.db_path)
            now_ts = int(time.time())
            
            if success:
                conn.execute("""
                    UPDATE edge_cameras 
                    SET last_capture_ts = ?,
                        last_success_ts = ?,
                        consecutive_failures = 0,
                        updated_at = ?
                    WHERE camera_id = ?
                """, (now_ts, now_ts, now_ts, camera_id))
            else:
                conn.execute("""
                    UPDATE edge_cameras 
                    SET last_capture_ts = ?,
                        consecutive_failures = consecutive_failures + 1,
                        updated_at = ?
                    WHERE camera_id = ?
                """, (now_ts, now_ts, camera_id))
                
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to update camera {camera_id} status: {e}")


class CameraTrigger:
    """Handles triggering edge cameras via HTTP."""
    
    def __init__(self, timeout_s: float, endpoint: str):
        self.timeout = timeout_s
        self.endpoint = endpoint
        
    def trigger(self, camera: Dict) -> bool:
        """
        Trigger a camera to capture and analyze.
        
        Returns:
            True if successful, False otherwise
        """
        camera_id = camera['camera_id']
        camera_name = camera['name']
        url = f"{camera['endpoint_url']}{self.endpoint}"
        
        try:
            payload = {
                "trigger": "scheduled",
                "timestamp": int(time.time()),
                "scheduler_id": "main"
            }
            
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            
            if config['logging']['log_captures']:
                logger.info(f"✓ Triggered camera {camera_id} ({camera_name})")
            
            return True
            
        except requests.RequestException as e:
            if config['logging']['log_failures']:
                logger.warning(f"✗ Failed to trigger camera {camera_id} ({camera_name}): {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error triggering camera {camera_id}: {e}")
            return False


class SchedulerDaemon:
    """Main scheduler daemon that orchestrates edge cameras."""
    
    def __init__(self):
        self.registry = CameraRegistry(
            db_path=DB_PATH,
            refresh_interval_s=config['database']['camera_refresh_interval_s']
        )
        self.trigger = CameraTrigger(
            timeout_s=config['edge_camera']['trigger_timeout_s'],
            endpoint=config['edge_camera']['trigger_endpoint']
        )
        self.tick_interval = config['scheduler']['tick_interval_s']
        self.max_concurrent = config['scheduler']['max_concurrent_captures']
        self.running = False
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent)
        
    def start(self):
        """Start the scheduler daemon main loop."""
        logger.info("="*60)
        logger.info("EchoBell Scheduler Daemon Starting")
        logger.info(f"Database: {DB_PATH}")
        logger.info(f"Tick Interval: {self.tick_interval}s")
        logger.info(f"Max Concurrent: {self.max_concurrent}")
        logger.info("="*60)
        
        # Initial camera load
        self.registry.refresh()
        
        self.running = True
        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.stop()
            
    def stop(self):
        """Stop the scheduler daemon."""
        logger.info("Shutting down scheduler daemon...")
        self.running = False
        self.executor.shutdown(wait=True)
        logger.info("Scheduler daemon stopped")
        
    def _main_loop(self):
        """Main scheduler loop - runs every tick_interval."""
        while self.running:
            try:
                now_ts = int(time.time())
                
                # Refresh camera registry if needed
                self.registry.refresh_if_needed()
                
                # Get cameras needing capture
                cameras_due = self.registry.get_cameras_needing_capture(now_ts)
                
                if cameras_due:
                    logger.debug(f"{len(cameras_due)} camera(s) due for capture")
                    self._trigger_cameras(cameras_due)
                
                # Sleep until next tick
                time.sleep(self.tick_interval)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(self.tick_interval)
                
    def _trigger_cameras(self, cameras: List[Dict]):
        """Trigger multiple cameras concurrently."""
        futures = []
        
        for camera in cameras:
            future = self.executor.submit(self._trigger_single_camera, camera)
            futures.append((future, camera['camera_id']))
            
        # Wait for all triggers to complete
        for future, camera_id in futures:
            try:
                success = future.result(timeout=self.trigger.timeout + 5)
                self.registry.update_capture_status(camera_id, success)
            except Exception as e:
                logger.error(f"Failed to complete trigger for camera {camera_id}: {e}")
                self.registry.update_capture_status(camera_id, False)
                
    def _trigger_single_camera(self, camera: Dict) -> bool:
        """Trigger a single camera (runs in thread pool)."""
        return self.trigger.trigger(camera)


if __name__ == "__main__":
    daemon = SchedulerDaemon()
    daemon.start()
