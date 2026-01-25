"""
Action Executor for Policy Engine
Executes actions triggered by policy matches (telegram, speak, webhook).

Uses plugin-based action handler registry for extensibility.
"""
from typing import Dict, Any, List
import sqlite3
import logging
from .action_handlers import ActionRegistry

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes actions from policy matches using registered handlers"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute_actions(
        self,
        actions: List[Dict[str, Any]],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute all actions with variable substitution using registered handlers.
        
        Args:
            actions: List of action dicts from policy
            variables: Resolved variable values
            context: Track context (camera_id, track_key, etc.)
        
        Returns:
            List of action results with {action_type, success, error}
        """
        results = []
        
        for action in actions:
            action_type = action.get('type')
            
            try:
                # Get handler from registry
                handler = ActionRegistry.get_handler(action_type, self.conn)
                
                if handler:
                    result = await handler.execute(action, variables, context)
                else:
                    logger.warning(f"No handler registered for action type: {action_type}")
                    result = {
                        'action_type': action_type,
                        'success': False,
                        'error': f'No handler registered for action type: {action_type}'
                    }
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"Action execution failed: {action_type} - {e}")
                results.append({
                    'action_type': action_type,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    def list_available_actions(self) -> List[str]:
        """List all registered action types"""
        return ActionRegistry.list_handlers()
