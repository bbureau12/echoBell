"""
Create Watch Action Handler

Allows policies to create time-based watches for deferred evaluation.

Example usage in policy:
    actions:
      - type: create_watch
        watch_type: "loitering_2min"
        due_in_seconds: 120
        expires_in_seconds: 600  # Optional, default: 300
"""
import sqlite3
import logging
from typing import Dict, Any
from ..action_handlers import register_action_handler, substitute_variables
from ..watch_service import WatchService

logger = logging.getLogger(__name__)


@register_action_handler("create_watch")
class CreateWatchActionHandler:
    """
    Create a time-based watch for deferred policy evaluation.
    
    Watches enable:
    - Loitering detection (alert after N minutes if person still present)
    - Delivery timeouts (alert if package not picked up)
    - Vehicle idling (alert if car parked too long)
    - Escalation chains (2min → 5min → 10min alerts)
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.watch_service = WatchService(db_path=":memory:")  # db_path not used with conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute watch creation action.
        
        Args:
            action: Dict with:
                - watch_type: Type of watch (e.g., "loitering_2min")
                - due_in_seconds: Seconds from now when watch should fire
                - expires_in_seconds: Optional expiration (default: 300)
                - context: Optional context dict for debugging
            variables: Substitution variables
            context: Runtime context with camera_id, scene_track_id, event_id, etc.
        
        Returns:
            Dict with success status and watch details
        """
        try:
            # Get required fields
            watch_type = substitute_variables(action.get('watch_type', ''), variables)
            due_in_seconds = action.get('due_in_seconds')
            
            if not watch_type:
                return {
                    'action_type': 'create_watch',
                    'success': False,
                    'error': 'Missing required field: watch_type'
                }
            
            if not due_in_seconds:
                return {
                    'action_type': 'create_watch',
                    'success': False,
                    'error': 'Missing required field: due_in_seconds'
                }
            
            # Get context fields
            camera_id = context.get('camera_id')
            scene_track_id = context.get('scene_track_id')
            event_id = context.get('event_id')
            created_by_policy_id = context.get('policy_id')
            
            if not camera_id:
                return {
                    'action_type': 'create_watch',
                    'success': False,
                    'error': 'Missing camera_id in context'
                }
            
            # Build watch_key for deduplication
            # Pattern: cam{id}:track_{track_key}:{watch_type}
            if scene_track_id:
                # Get track_key from scene_tracks
                cursor = self.conn.execute(
                    "SELECT track_key FROM scene_tracks WHERE id = ?",
                    (scene_track_id,)
                )
                row = cursor.fetchone()
                track_key = row[0] if row else f"track_{scene_track_id}"
                watch_key = f"cam{camera_id}:track_{track_key}:{watch_type}"
            else:
                # No track, use event_id or timestamp
                watch_key = f"cam{camera_id}:{watch_type}:{event_id or context.get('timestamp', '')}"
            
            # Optional fields
            expires_in_seconds = action.get('expires_in_seconds')
            watch_context = action.get('context', {})
            
            # Merge action context with runtime context for debugging
            full_context = {
                'created_by_policy_id': created_by_policy_id,
                'event_id': event_id,
                **watch_context
            }
            
            # Create watch
            watch = self.watch_service.create_watch(
                conn=self.conn,
                watch_type=watch_type,
                watch_key=watch_key,
                camera_id=camera_id,
                due_in_seconds=due_in_seconds,
                scene_track_id=scene_track_id,
                event_id=event_id,
                expires_in_seconds=expires_in_seconds,
                context=full_context,
                created_by_policy_id=created_by_policy_id
            )
            
            if watch:
                logger.info(
                    f"Created watch: {watch_type} (key={watch_key}, due_in={due_in_seconds}s, "
                    f"camera={camera_id}, track={scene_track_id})"
                )
                return {
                    'action_type': 'create_watch',
                    'success': True,
                    'watch_id': watch.id,
                    'watch_key': watch.watch_key,
                    'watch_type': watch.watch_type,
                    'due_ts': watch.due_ts,
                    'expires_ts': watch.expires_ts
                }
            else:
                # Duplicate watch_key - already exists
                logger.debug(
                    f"Watch already exists: {watch_type} (key={watch_key})"
                )
                return {
                    'action_type': 'create_watch',
                    'success': True,
                    'duplicate': True,
                    'watch_key': watch_key,
                    'message': 'Watch with this key already exists (deduplication)'
                }
                
        except Exception as e:
            logger.error(f"Failed to create watch: {e}", exc_info=True)
            return {
                'action_type': 'create_watch',
                'success': False,
                'error': str(e)
            }
