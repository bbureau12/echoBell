"""
Action Handler Registry for Policy Engine
Extensible plugin-based system for executing policy actions.

Usage:
    1. Create handler class implementing ActionHandler protocol
    2. Register with @register_action_handler("action_type") decorator
    3. Handler automatically available to executor

Example:
    @register_action_handler("my_custom_action")
    class MyCustomActionHandler(ActionHandler):
        async def execute(self, action, variables, context):
            # Your implementation here
            return {"success": True, "result": "..."}
"""
from typing import Dict, Any, Protocol, Optional, Callable
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# Action Handler Protocol
# ============================================================================

class ActionHandler(Protocol):
    """
    Protocol for action handlers.
    All handlers must implement the execute method.
    """
    
    def __init__(self, conn: sqlite3.Connection):
        """Initialize handler with database connection"""
        ...
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute the action.
        
        Args:
            action: Action definition from policy (type, config, etc.)
            variables: Resolved variable values for substitution
            context: Runtime context (camera_id, track_key, timestamp, etc.)
        
        Returns:
            Dict with at minimum: {"success": bool, "action_type": str}
            Optional keys: "error", "message", "data", etc.
        """
        ...


# ============================================================================
# Action Registry
# ============================================================================

class ActionRegistry:
    """Global registry of action handlers"""
    
    _handlers: Dict[str, type] = {}
    
    @classmethod
    def register(cls, action_type: str, handler_class: type):
        """Register a handler class for an action type"""
        if action_type in cls._handlers:
            logger.warning(f"Overwriting existing handler for action type: {action_type}")
        cls._handlers[action_type] = handler_class
        logger.debug(f"Registered action handler: {action_type} -> {handler_class.__name__}")
    
    @classmethod
    def get_handler(cls, action_type: str, conn: sqlite3.Connection) -> Optional[ActionHandler]:
        """Get an instance of the handler for the given action type"""
        handler_class = cls._handlers.get(action_type)
        if handler_class:
            return handler_class(conn)
        return None
    
    @classmethod
    def list_handlers(cls) -> list[str]:
        """List all registered action types"""
        return list(cls._handlers.keys())


# ============================================================================
# Registration Decorator
# ============================================================================

def register_action_handler(action_type: str) -> Callable:
    """
    Decorator to register an action handler.
    
    Usage:
        @register_action_handler("my_action")
        class MyActionHandler:
            def __init__(self, conn): ...
            async def execute(self, action, variables, context): ...
    """
    def decorator(handler_class: type) -> type:
        ActionRegistry.register(action_type, handler_class)
        return handler_class
    return decorator


# ============================================================================
# Utility Functions for Handlers
# ============================================================================

def substitute_variables(template: str, variables: Dict[str, str]) -> str:
    """
    Substitute {variable} placeholders in a string.
    
    Example:
        substitute_variables("Hello {name}!", {"name": "World"})
        # Returns: "Hello World!"
    """
    import re
    
    def replacer(match):
        var_name = match.group(1)
        return str(variables.get(var_name, match.group(0)))
    
    return re.sub(r'\{(\w+)\}', replacer, template)


def substitute_variables_in_dict(data: Dict[str, Any], variables: Dict[str, str]) -> Dict[str, Any]:
    """
    Recursively substitute variables in dict values.
    
    Example:
        substitute_variables_in_dict(
            {"message": "Hello {name}!", "count": "{count}"},
            {"name": "World", "count": "5"}
        )
        # Returns: {"message": "Hello World!", "count": "5"}
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = substitute_variables(value, variables)
        elif isinstance(value, dict):
            result[key] = substitute_variables_in_dict(value, variables)
        elif isinstance(value, list):
            result[key] = [
                substitute_variables_in_dict(item, variables) if isinstance(item, dict)
                else substitute_variables(item, variables) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def record_alert_history(
    conn: sqlite3.Connection,
    context: Dict[str, Any],
    alert_type: str,
    message: str,
    priority: str = "normal",
    success: bool = True,
    error_message: Optional[str] = None
):
    """
    Record alert in alert_history table for spam prevention and audit.
    
    Args:
        conn: Database connection
        context: Context dict with camera_id, track_key, track_type
        alert_type: Type of alert (telegram, speak, sms, etc.)
        message: Alert message
        priority: Priority level (low, normal, urgent)
        success: Whether alert was sent successfully
        error_message: Error message if failed
    """
    track_key = context.get('track_key')
    camera_id = context.get('camera_id')
    track_type = context.get('track_type', 'unknown')
    policy_id = context.get('policy_id')
    
    if not track_key or not camera_id:
        logger.warning("Missing track_key or camera_id - skipping alert_history record")
        return
    
    try:
        conn.execute("""
            INSERT INTO alert_history
            (camera_id, track_key, track_type, policy_id, alert_type, 
             message, priority, sent_ts, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            camera_id,
            track_key,
            track_type,
            policy_id,
            alert_type,
            message,
            priority,
            int(datetime.now().timestamp()),
            1 if success else 0,
            error_message
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to record alert history: {e}")


# ============================================================================
# Built-in Action Handlers
# ============================================================================

@register_action_handler("telegram")
class TelegramActionHandler:
    """Send Telegram message"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send Telegram notification"""
        from packages.integrations.telegram import load_telegram_config, TelegramNotifier
        
        message = substitute_variables(action.get('message', ''), variables)
        priority = action.get('priority', 'normal')
        send_photo = action.get('send_photo', False)
        photo_path = action.get('photo_path')
        
        # Substitute variables in photo_path if provided
        if photo_path:
            photo_path = substitute_variables(photo_path, variables)
        
        # If no photo_path but snapshot_url available, use it
        # (Edge device scenario - context has snapshot_url from edge image server)
        if not photo_path and send_photo:
            if 'snapshot_url' in variables:
                photo_path = variables['snapshot_url']
                logger.info(f"[TELEGRAM] Using snapshot_url from context: {photo_path}")
            elif 'snapshot_path' in variables:
                photo_path = variables['snapshot_path']
                logger.info(f"[TELEGRAM] Using snapshot_path from context: {photo_path}")
        
        # Load Telegram config
        config = load_telegram_config()
        if not config or not config.enabled:
            logger.warning("Telegram not configured or disabled")
            return {
                'action_type': 'telegram',
                'success': False,
                'error': 'Telegram not configured or disabled'
            }
        
        # Send notification
        notifier = TelegramNotifier(config)
        success = False
        error_msg = None
        
        try:
            if send_photo and photo_path:
                logger.info(f"[TELEGRAM] Attempting to send photo: {photo_path}")
                
                # Check if photo_path is a URL
                import os
                import tempfile
                import requests
                from pathlib import Path
                
                local_photo_path = photo_path
                temp_file = None
                
                if photo_path.startswith(('http://', 'https://')):
                    # Download image from URL
                    logger.info(f"[TELEGRAM] Downloading image from URL: {photo_path}")
                    try:
                        # Add X-API-Key header for edge device authentication
                        # TODO: Make this configurable per edge device
                        headers = {
                            'X-API-Key': 'dontgiveitupluffy'  # Dev/test API key
                        }
                        
                        response = requests.get(photo_path, timeout=10, headers=headers)
                        response.raise_for_status()
                        
                        # Create downloaded images directory
                        download_dir = Path("data/downloaded_images")
                        download_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Generate temp filename from URL or use timestamp
                        import time
                        filename = os.path.basename(photo_path.split('?')[0])  # Remove query params
                        if not filename or '.' not in filename:
                            filename = f"download_{int(time.time())}.jpg"
                        
                        temp_file = download_dir / filename
                        
                        # Save downloaded image
                        with open(temp_file, 'wb') as f:
                            f.write(response.content)
                        
                        local_photo_path = str(temp_file)
                        logger.info(f"[TELEGRAM] Downloaded to: {local_photo_path}")
                        
                    except requests.RequestException as e:
                        error_msg = f"Failed to download image from {photo_path}: {e}"
                        logger.error(f"[TELEGRAM] {error_msg}")
                        return {
                            'action_type': 'telegram',
                            'success': False,
                            'error': error_msg,
                            'message': message
                        }
                
                # Check if local file exists
                if not os.path.exists(local_photo_path):
                    # Try with absolute path
                    abs_path = os.path.abspath(local_photo_path)
                    if os.path.exists(abs_path):
                        logger.info(f"[TELEGRAM] Using absolute path: {abs_path}")
                        local_photo_path = abs_path
                    else:
                        error_msg = f"Photo file not found: {local_photo_path} (also tried {abs_path})"
                        logger.error(f"[TELEGRAM] {error_msg}")
                        return {
                            'action_type': 'telegram',
                            'success': False,
                            'error': error_msg,
                            'message': message
                        }
                
                logger.info(f"[TELEGRAM] Sending photo with caption: {message[:50]}...")
                success = notifier.send_photo(local_photo_path, caption=message)
                
                if success:
                    logger.info(f"[TELEGRAM] ✓ Photo sent successfully")
                else:
                    logger.warning(f"[TELEGRAM] ✗ Photo send returned False")
            else:
                if send_photo:
                    logger.warning(f"[TELEGRAM] send_photo=True but no photo_path provided")
                success = notifier.send_message(message)
            
            if not success:
                error_msg = "Telegram API returned False (check bot token/chat ID)"
            
            # Record in alert_history
            record_alert_history(
                self.conn,
                context,
                alert_type='telegram',
                message=message,
                priority=priority,
                success=success,
                error_message=error_msg
            )
            
            logger.info(f"[TELEGRAM] {priority.upper()}: {message} - {'✓' if success else '✗'}")
            
            result = {
                'action_type': 'telegram',
                'success': success,
                'message': message,
                'priority': priority
            }
            if error_msg:
                result['error'] = error_msg
            
            return result
            
        except Exception as e:
            logger.error(f"Telegram action failed: {e}")
            record_alert_history(
                self.conn,
                context,
                alert_type='telegram',
                message=message,
                priority=priority,
                success=False,
                error_message=str(e)
            )
            return {
                'action_type': 'telegram',
                'success': False,
                'error': str(e)
            }


@register_action_handler("speak")
class SpeakActionHandler:
    """Text-to-speech action"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute TTS speech"""
        from packages.tts.piper import speak
        
        text = substitute_variables(action.get('text', ''), variables)
        voice = action.get('voice', 'default')
        
        logger.info(f"[SPEAK] {voice}: {text}")
        
        try:
            # Call TTS service
            speak(text)
            
            return {
                'action_type': 'speak',
                'success': True,
                'text': text,
                'voice': voice
            }
        except Exception as e:
            logger.error(f"Speak action failed: {e}")
            return {
                'action_type': 'speak',
                'success': False,
                'error': str(e)
            }


@register_action_handler("webhook")
class WebhookActionHandler:
    """HTTP webhook action"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call external webhook"""
        import httpx
        
        url = substitute_variables(action.get('url', ''), variables)
        method = action.get('method', 'POST').upper()
        payload = action.get('payload', {})
        headers = action.get('headers', {})
        timeout = action.get('timeout', 5.0)
        
        # Substitute variables in payload
        payload = substitute_variables_in_dict(payload, variables)
        
        logger.info(f"[WEBHOOK] {method} {url} - {payload}")
        
        try:
            async with httpx.AsyncClient() as client:
                if method == 'POST':
                    response = await client.post(url, json=payload, headers=headers, timeout=timeout)
                elif method == 'GET':
                    response = await client.get(url, params=payload, headers=headers, timeout=timeout)
                elif method == 'PUT':
                    response = await client.put(url, json=payload, headers=headers, timeout=timeout)
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
                    'method': method,
                    'url': url,
                    'status_code': response.status_code
                }
                
        except Exception as e:
            logger.error(f"Webhook action failed: {e}")
            return {
                'action_type': 'webhook',
                'success': False,
                'error': str(e),
                'url': url
            }


@register_action_handler("log")
class LogActionHandler:
    """Simple logging action (for debugging/testing)"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Log message to console"""
        message = substitute_variables(action.get('message', ''), variables)
        level = action.get('level', 'INFO').upper()
        
        log_func = getattr(logger, level.lower(), logger.info)
        log_func(f"[POLICY LOG] {message}")
        
        return {
            'action_type': 'log',
            'success': True,
            'message': message,
            'level': level
        }
