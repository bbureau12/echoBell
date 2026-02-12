"""
Watch Worker - Background evaluator for time-based policy watches

This worker runs as a background task in the policy server and:
1. Fetches watches that are due (due_ts <= now)
2. Builds current scene evidence
3. Re-evaluates ALL policies with watch-triggered evidence
4. Executes matched policy actions
5. Updates watch state (triggered/disarmed/expired)

Example flow:
    T+0s:  Unknown person detected → policy creates watch (due in 120s)
    T+120s: Worker fires → checks if person still present → alerts
    T+120s: Alert policy creates next watch (due in 180s) for escalation
    T+300s: Worker fires → checks if person still present → escalates
"""

import asyncio
import logging
import sqlite3
import time
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from packages.policy.watch_service import WatchService, Watch, WatchState
from packages.policy.evaluator import PolicyEvaluator
from packages.policy.executor import ActionExecutor
from packages.common.types import Evidence

logger = logging.getLogger(__name__)


class WatchWorker:
    """Background worker for evaluating time-based watches."""
    
    def __init__(
        self,
        db_path: str,
        poll_interval_seconds: int = 5,
        expire_check_interval_seconds: int = 60
    ):
        """
        Initialize watch worker.
        
        Args:
            db_path: Path to SQLite database
            poll_interval_seconds: How often to check for due watches
            expire_check_interval_seconds: How often to expire old watches
        """
        self.db_path = db_path
        self.poll_interval = poll_interval_seconds
        self.expire_check_interval = expire_check_interval_seconds
        
        self.watch_service = WatchService(db_path)
        self.running = False
        self.task: Optional[asyncio.Task] = None
        
        self._last_expire_check = 0
    
    @contextmanager
    def _get_db(self):
        """Get database connection (context manager)."""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    async def start(self):
        """Start the watch worker background task."""
        if self.running:
            logger.warning("Watch worker already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._worker_loop())
        logger.info(
            f"Watch worker started (poll={self.poll_interval}s, "
            f"expire_check={self.expire_check_interval}s)"
        )
    
    async def stop(self):
        """Stop the watch worker."""
        if not self.running:
            return
        
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("Watch worker stopped")
    
    async def _worker_loop(self):
        """Main worker loop."""
        logger.info("Watch worker loop started")
        
        while self.running:
            try:
                # Evaluate due watches
                await self._evaluate_due_watches()
                
                # Periodically expire old watches
                now = int(time.time())
                if now - self._last_expire_check > self.expire_check_interval:
                    await self._expire_old_watches()
                    self._last_expire_check = now
                
                # Sleep until next poll
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watch worker error: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)
    
    async def _evaluate_due_watches(self):
        """Fetch and evaluate all watches that are due."""
        with self._get_db() as conn:
            # Get due watches
            due_watches = self.watch_service.get_due_watches(conn)
            
            if not due_watches:
                return
            
            logger.info(f"Evaluating {len(due_watches)} due watches")
            
            for watch in due_watches:
                try:
                    await self._evaluate_watch(conn, watch)
                except Exception as e:
                    logger.error(
                        f"Failed to evaluate watch {watch.id} ({watch.watch_type}): {e}",
                        exc_info=True
                    )
                    # Mark as disarmed on error to prevent retry loop
                    self.watch_service.mark_disarmed(
                        conn,
                        watch.id,
                        trigger_reason=f"error: {str(e)}"
                    )
    
    async def _evaluate_watch(self, conn: sqlite3.Connection, watch: Watch):
        """
        Evaluate a single watch.
        
        Args:
            conn: Database connection
            watch: Watch to evaluate
        """
        logger.debug(
            f"Evaluating watch {watch.id}: {watch.watch_type} "
            f"(camera={watch.camera_id}, track={watch.scene_track_id})"
        )
        
        # Check if scene track is still active (if watch is track-based)
        if watch.scene_track_id:
            cursor = conn.execute(
                "SELECT active, track_key, first_seen_ts, track_type FROM scene_tracks WHERE id = ?",
                (watch.scene_track_id,)
            )
            row = cursor.fetchone()
            
            if not row or not row[0]:
                # Track no longer active - disarm watch
                logger.info(
                    f"Watch {watch.id} disarmed: scene track {watch.scene_track_id} "
                    "no longer active"
                )
                self.watch_service.mark_disarmed(
                    conn,
                    watch.id,
                    trigger_reason="track_inactive"
                )
                return
            
            track_key = row[1]
            first_seen_ts = row[2]
            track_type = row[3]
        else:
            track_key = None
            first_seen_ts = None
            track_type = None
        
        # Build evidence context from current scene state
        evidence = await self._build_watch_evidence(conn, watch, track_key, first_seen_ts)
        
        # Add watch-triggered evidence
        evidence.append({
            'source': 'watch',
            'feature': 'triggered',
            'value': watch.watch_type,
            'conf': 1.0
        })
        
        # Build context for policy evaluation
        now = int(time.time())
        context = {
            'camera_id': watch.camera_id,
            'scene_track_id': watch.scene_track_id,
            'event_id': watch.event_id,
            'watch_id': watch.id,
            'watch_type': watch.watch_type,
            'timestamp': now,
        }
        
        # Add track_key and track_type for alert history checks
        if track_key:
            context['track_key'] = track_key
        if track_type:
            context['track_type'] = track_type
        
        # Add track duration if applicable
        if first_seen_ts:
            context['track_duration_seconds'] = now - first_seen_ts
        
        # Evaluate ALL policies
        evaluator = PolicyEvaluator(conn, use_database=True)
        matches = evaluator.evaluate_all(evidence, context)
        
        if matches:
            logger.info(
                f"Watch {watch.id} triggered {len(matches)} policy matches: "
                f"{[m.policy_id for m in matches]}"
            )
            
            # Execute matched policy actions
            executor = ActionExecutor(conn)
            for match in matches:
                try:
                    # Add policy_id to context for action handlers
                    action_context = {**context, 'policy_id': match.policy_id}
                    results = await executor.execute_actions(
                        match.actions,
                        match.variables,
                        action_context
                    )
                    
                    for result in results:
                        if result['success']:
                            logger.info(
                                f"  ✓ {result['action_type']} "
                                f"(policy={match.policy_id})"
                            )
                        else:
                            logger.warning(
                                f"  ✗ {result['action_type']} failed: "
                                f"{result.get('error')} (policy={match.policy_id})"
                            )
                            
                except Exception as e:
                    logger.error(
                        f"Failed to execute actions for policy {match.policy_id}: {e}",
                        exc_info=True
                    )
            
            # Mark watch as triggered
            self.watch_service.mark_triggered(
                conn,
                watch.id,
                trigger_reason=f"policies_matched: {', '.join(m.policy_id for m in matches)}"
            )
        else:
            logger.debug(f"Watch {watch.id} disarmed: no policies matched")
            self.watch_service.mark_disarmed(
                conn,
                watch.id,
                trigger_reason="no_policies_matched"
            )
    
    async def _build_watch_evidence(
        self,
        conn: sqlite3.Connection,
        watch: Watch,
        track_key: Optional[str],
        first_seen_ts: Optional[int]
    ) -> List[Dict[str, Any]]:
        """
        Build evidence from current scene state for watch evaluation.
        
        Args:
            conn: Database connection
            watch: Watch being evaluated
            track_key: Scene track key (if available)
            first_seen_ts: Track first seen timestamp (if available)
            
        Returns:
            List of evidence dicts
        """
        evidence = []
        now = int(time.time())
        
        # If track-based, get current track state
        if watch.scene_track_id and track_key:
            # Get track type (person, vehicle, etc.)
            cursor = conn.execute(
                "SELECT track_type FROM scene_tracks WHERE id = ?",
                (watch.scene_track_id,)
            )
            row = cursor.fetchone()
            track_type = row[0] if row else "unknown"
            
            # Add scene evidence
            evidence.append({
                'source': 'scene',
                'feature': f'{track_type}_present',
                'value': 'true',
                'conf': 1.0
            })
            
            # Add track duration
            if first_seen_ts:
                duration = now - first_seen_ts
                evidence.append({
                    'source': 'scene',
                    'feature': 'track_duration_seconds',
                    'value': str(duration),
                    'conf': 1.0
                })
        
        # Camera context
        evidence.append({
            'source': 'context',
            'feature': 'camera_id',
            'value': str(watch.camera_id),
            'conf': 1.0
        })
        
        return evidence
    
    async def _expire_old_watches(self):
        """Expire watches that have passed their expires_ts."""
        with self._get_db() as conn:
            expired_count = self.watch_service.expire_old_watches(conn)
            if expired_count > 0:
                logger.info(f"Expired {expired_count} old watches")
    
    async def cleanup_old_watches(self, days_old: int = 30):
        """
        Hard-delete watches older than N days (manual trigger).
        
        Args:
            days_old: Delete watches older than this many days
        """
        with self._get_db() as conn:
            deleted_count = self.watch_service.cleanup_old_watches(conn, days_old)
            logger.info(f"Cleaned up {deleted_count} watches older than {days_old} days")
            return deleted_count
