"""
Reclassify Action Handler

Allows policies to override visitor intent classification based on temporal context,
scheduled events, or other policy conditions.

Example usage in policy:
    actions:
      - type: reclassify
        event_id: "{event_id}"        # From context
        intent: "delivery_arriving"
        confidence: 0.85
        reason: "Active delivery expectation window"
"""
import sqlite3
import logging
from typing import Dict, Any
from ..action_handlers import register_action_handler, substitute_variables

logger = logging.getLogger(__name__)


@register_action_handler("reclassify")
class ReclassifyActionHandler:
    """
    Reclassify visitor intent based on policy-driven override.
    
    This allows temporal context (like scheduled delivery windows) to
    override low-confidence or uncertain classifications.
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute reclassification action.
        
        Args:
            action: Dict with:
                - event_id: Visitor event ID (or use context['event_id'])
                - intent: New intent to assign
                - confidence: New confidence score (0.0-1.0)
                - reason: Human-readable explanation
            variables: Substitution variables
            context: Runtime context with event_id, timestamp, etc.
        
        Returns:
            Dict with success status and reclassification details
        """
        try:
            # Get event_id (from action spec or context)
            event_id = action.get('event_id')
            if event_id and '{' in event_id:
                event_id = substitute_variables(event_id, variables)
            if not event_id:
                event_id = context.get('event_id')
            
            if not event_id:
                return {
                    'action_type': 'reclassify',
                    'success': False,
                    'error': 'No event_id provided in action or context'
                }
            
            # Get new intent and confidence
            new_intent = action.get('intent')
            new_confidence = action.get('confidence', 0.85)
            reason = substitute_variables(
                action.get('reason', 'Policy-driven reclassification'),
                variables
            )
            
            if not new_intent:
                return {
                    'action_type': 'reclassify',
                    'success': False,
                    'error': 'No intent specified for reclassification'
                }
            
            # Verify event exists
            cursor = self.conn.execute(
                "SELECT intent_inferred, intent_confidence FROM visitor_events WHERE event_id = ?",
                (event_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return {
                    'action_type': 'reclassify',
                    'success': False,
                    'error': f'Event {event_id} not found'
                }
            
            original_intent = row[0]
            original_confidence = row[1]
            
            # Check if already at target intent
            if original_intent == new_intent and abs(original_confidence - new_confidence) < 0.01:
                logger.info(
                    f"Event {event_id} already classified as {new_intent} "
                    f"(conf={original_confidence:.2f}), skipping reclassification"
                )
                return {
                    'action_type': 'reclassify',
                    'success': True,
                    'skipped': True,
                    'event_id': event_id,
                    'intent': new_intent,
                    'reason': 'Already at target classification'
                }
            
            # Perform reclassification via services layer
            try:
                from central.policy_server import services
                
                result = services.reclassify_visitor_intent(
                    conn=self.conn,
                    event_id=event_id,
                    override_intent=new_intent,
                    override_confidence=new_confidence,
                    reason=reason,
                    reclassified_by="policy"
                )
                
                if result.get('success'):
                    logger.info(
                        f"Reclassified event {event_id}: "
                        f"{result['original_intent']} → {result['new_intent']} "
                        f"(conf: {result['original_confidence']:.2f} → {result['new_confidence']:.2f})"
                    )
                    
                    return {
                        'action_type': 'reclassify',
                        'success': True,
                        'event_id': event_id,
                        'original_intent': result['original_intent'],
                        'new_intent': result['new_intent'],
                        'original_confidence': result['original_confidence'],
                        'new_confidence': result['new_confidence'],
                        'reason': reason,
                        'changed': result.get('changed', True)
                    }
                else:
                    return {
                        'action_type': 'reclassify',
                        'success': False,
                        'error': result.get('error', 'Reclassification failed'),
                        'event_id': event_id
                    }
                    
            except ImportError:
                # Fallback: Direct database update if services not available
                logger.warning("Services layer not available, using direct database update")
                
                import time
                now_ts = int(time.time())
                
                # Check if reclassification columns exist
                cursor = self.conn.execute("PRAGMA table_info(visitor_events)")
                columns = [row[1] for row in cursor.fetchall()]
                has_reclass_columns = 'reclassified_by' in columns
                
                if has_reclass_columns:
                    self.conn.execute("""
                        UPDATE visitor_events
                        SET intent_inferred = ?,
                            intent_confidence = ?,
                            reclassified_by = 'policy',
                            reclassification_reason = ?,
                            reclassified_ts = ?,
                            reclassification_count = COALESCE(reclassification_count, 0) + 1
                        WHERE event_id = ?
                    """, (new_intent, new_confidence, reason, now_ts, event_id))
                else:
                    self.conn.execute("""
                        UPDATE visitor_events
                        SET intent_inferred = ?,
                            intent_confidence = ?
                        WHERE event_id = ?
                    """, (new_intent, new_confidence, event_id))
                
                self.conn.commit()
                
                logger.info(
                    f"Reclassified event {event_id}: "
                    f"{original_intent} → {new_intent} "
                    f"(conf: {original_confidence:.2f} → {new_confidence:.2f})"
                )
                
                return {
                    'action_type': 'reclassify',
                    'success': True,
                    'event_id': event_id,
                    'original_intent': original_intent,
                    'new_intent': new_intent,
                    'original_confidence': original_confidence,
                    'new_confidence': new_confidence,
                    'reason': reason,
                    'changed': True
                }
        
        except Exception as e:
            logger.error(f"Reclassify action failed: {e}", exc_info=True)
            return {
                'action_type': 'reclassify',
                'success': False,
                'error': str(e)
            }
