"""
Action Executor for Policy Engine
Executes actions triggered by policy matches (telegram, speak, webhook).
"""
from typing import Dict, Any, List, Optional
import sqlite3
from datetime import datetime
import re
import httpx
import logging

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes actions from policy matches"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute_actions(
        self,
        actions: List[Dict[str, Any]],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute all actions with variable substitution.
        
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
                if action_type == 'telegram':
                    result = await self._execute_telegram(action, variables, context)
                elif action_type == 'speak':
                    result = await self._execute_speak(action, variables, context)
                elif action_type == 'webhook':
                    result = await self._execute_webhook(action, variables, context)
                else:
                    result = {'action_type': action_type, 'success': False, 'error': 'Unknown action type'}
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"Action execution failed: {action_type} - {e}")
                results.append({
                    'action_type': action_type,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    async def _execute_telegram(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send Telegram notification"""
        message = self._substitute_variables(action.get('message', ''), variables)
        priority = action.get('priority', 'normal')
        
        # Record in alert_history
        track_key = context.get('track_key')
        camera_id = context.get('camera_id')
        
        if track_key and camera_id:
            self.conn.execute("""
                INSERT INTO alert_history
                (camera_id, track_key, alert_type, priority, sent_ts, message, success)
                VALUES (?, ?, 'telegram', ?, ?, ?, 1)
            """, (camera_id, track_key, priority, int(datetime.now().timestamp()), message))
            self.conn.commit()
        
        logger.info(f"[TELEGRAM] {priority.upper()}: {message}")
        
        # TODO: Actually send to Telegram bot API
        # For now, just log and return success
        return {
            'action_type': 'telegram',
            'success': True,
            'message': message,
            'priority': priority
        }
    
    async def _execute_speak(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute TTS speech"""
        text = self._substitute_variables(action.get('text', ''), variables)
        voice = action.get('voice', 'default')
        
        logger.info(f"[SPEAK] {voice}: {text}")
        
        # TODO: Call TTS service (packages/tts/piper.py)
        # For now, just log
        return {
            'action_type': 'speak',
            'success': True,
            'text': text,
            'voice': voice
        }
    
    async def _execute_webhook(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call external webhook (lights, security systems, etc.)"""
        url = self._substitute_variables(action.get('url', ''), variables)
        method = action.get('method', 'POST').upper()
        payload = action.get('payload', {})
        headers = action.get('headers', {})
        
        # Substitute variables in payload
        payload = self._substitute_variables_in_dict(payload, variables)
        
        logger.info(f"[WEBHOOK] {method} {url} - {payload}")
        
        try:
            async with httpx.AsyncClient() as client:
                if method == 'POST':
                    response = await client.post(url, json=payload, headers=headers, timeout=5.0)
                elif method == 'GET':
                    response = await client.get(url, params=payload, headers=headers, timeout=5.0)
                elif method == 'PUT':
                    response = await client.put(url, json=payload, headers=headers, timeout=5.0)
                else:
                    return {
                        'action_type': 'webhook',
                        'success': False,
                        'error': f'Unsupported HTTP method: {method}'
                    }
                
                response.raise_for_status()
                
                return {
                    'action_type': 'webhook',
                    'success': True,
                    'url': url,
                    'status_code': response.status_code,
                    'response': response.text[:200]  # Truncate response
                }
        
        except httpx.HTTPStatusError as e:
            return {
                'action_type': 'webhook',
                'success': False,
                'url': url,
                'status_code': e.response.status_code,
                'error': str(e)
            }
        except Exception as e:
            return {
                'action_type': 'webhook',
                'success': False,
                'url': url,
                'error': str(e)
            }
    
    def _substitute_variables(self, text: str, variables: Dict[str, str]) -> str:
        """Replace {variable_name} placeholders in text"""
        result = text
        for var_name, var_value in variables.items():
            result = result.replace(f'{{{var_name}}}', str(var_value))
        return result
    
    def _substitute_variables_in_dict(self, data: Dict[str, Any], variables: Dict[str, str]) -> Dict[str, Any]:
        """Recursively substitute variables in dict/list structures"""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._substitute_variables(value, variables)
            elif isinstance(value, dict):
                result[key] = self._substitute_variables_in_dict(value, variables)
            elif isinstance(value, list):
                result[key] = [
                    self._substitute_variables(v, variables) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result
