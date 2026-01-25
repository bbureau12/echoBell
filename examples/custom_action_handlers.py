"""
Example: Custom Action Handlers
Demonstrates how to create and register custom action handlers.
"""
from typing import Dict, Any
import sqlite3
import logging
from packages.policy.action_handlers import (
    register_action_handler,
    substitute_variables,
    record_alert_history
)

logger = logging.getLogger(__name__)


# ============================================================================
# Example 1: SMS Action Handler
# ============================================================================

@register_action_handler("sms")
class SMSActionHandler:
    """
    Send SMS via Twilio or similar service.
    
    Action config:
        type: sms
        to: "+1234567890"
        message: "Alert: {vehicle_color} {vehicle_type} detected"
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send SMS notification"""
        to_number = substitute_variables(action.get('to', ''), variables)
        message = substitute_variables(action.get('message', ''), variables)
        
        logger.info(f"[SMS] To: {to_number}, Message: {message}")
        
        # TODO: Integrate with Twilio API
        # from twilio.rest import Client
        # client = Client(account_sid, auth_token)
        # client.messages.create(to=to_number, from_=from_number, body=message)
        
        # Record in alert_history
        record_alert_history(
            self.conn,
            context,
            alert_type='sms',
            message=message,
            priority=action.get('priority', 'normal'),
            success=True
        )
        
        return {
            'action_type': 'sms',
            'success': True,
            'to': to_number,
            'message': message
        }


# ============================================================================
# Example 2: Home Assistant Integration
# ============================================================================

@register_action_handler("home_assistant")
class HomeAssistantActionHandler:
    """
    Trigger Home Assistant automations or services.
    
    Action config:
        type: home_assistant
        entity_id: "light.driveway"
        service: "turn_on"
        data:
          brightness: 255
          color_name: "red"
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call Home Assistant service"""
        import httpx
        import os
        
        entity_id = substitute_variables(action.get('entity_id', ''), variables)
        service = action.get('service', 'turn_on')
        data = action.get('data', {})
        
        # Substitute variables in data
        from packages.policy.action_handlers import substitute_variables_in_dict
        data = substitute_variables_in_dict(data, variables)
        
        # Get Home Assistant config from environment
        ha_url = os.getenv('HOME_ASSISTANT_URL', 'http://homeassistant.local:8123')
        ha_token = os.getenv('HOME_ASSISTANT_TOKEN', '')
        
        if not ha_token:
            logger.warning("HOME_ASSISTANT_TOKEN not set")
            return {
                'action_type': 'home_assistant',
                'success': False,
                'error': 'HOME_ASSISTANT_TOKEN not configured'
            }
        
        # Determine domain from entity_id (e.g., "light" from "light.driveway")
        domain = entity_id.split('.')[0] if '.' in entity_id else 'automation'
        
        url = f"{ha_url}/api/services/{domain}/{service}"
        headers = {
            'Authorization': f'Bearer {ha_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            'entity_id': entity_id,
            **data
        }
        
        logger.info(f"[HOME ASSISTANT] {domain}.{service} on {entity_id} - {data}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=5.0)
                response.raise_for_status()
                
                return {
                    'action_type': 'home_assistant',
                    'success': True,
                    'entity_id': entity_id,
                    'service': service,
                    'status_code': response.status_code
                }
                
        except Exception as e:
            logger.error(f"Home Assistant action failed: {e}")
            return {
                'action_type': 'home_assistant',
                'success': False,
                'error': str(e)
            }


# ============================================================================
# Example 3: Database Logger (for analytics)
# ============================================================================

@register_action_handler("db_log")
class DatabaseLogActionHandler:
    """
    Log events to a custom analytics table.
    
    Action config:
        type: db_log
        table: "security_events"
        data:
          event_type: "loitering"
          severity: "high"
          duration_minutes: "{duration_minutes}"
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Log to database table"""
        from datetime import datetime
        from packages.policy.action_handlers import substitute_variables_in_dict
        
        table = action.get('table', 'custom_events')
        data = action.get('data', {})
        
        # Substitute variables in data
        data = substitute_variables_in_dict(data, variables)
        
        # Add context fields
        data['camera_id'] = context.get('camera_id')
        data['track_key'] = context.get('track_key')
        data['timestamp'] = int(datetime.now().timestamp())
        
        # Build INSERT query
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        logger.info(f"[DB_LOG] {table}: {data}")
        
        try:
            self.conn.execute(query, tuple(data.values()))
            self.conn.commit()
            
            return {
                'action_type': 'db_log',
                'success': True,
                'table': table,
                'data': data
            }
            
        except Exception as e:
            logger.error(f"Database log failed: {e}")
            return {
                'action_type': 'db_log',
                'success': False,
                'error': str(e)
            }


# ============================================================================
# Example 4: Email Action Handler
# ============================================================================

@register_action_handler("email")
class EmailActionHandler:
    """
    Send email notifications.
    
    Action config:
        type: email
        to: "user@example.com"
        subject: "Security Alert: {vehicle_type} detected"
        body: "A {vehicle_color} {vehicle_type} was detected at {timestamp}"
        attach_snapshot: true
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send email notification"""
        import os
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        to_addr = substitute_variables(action.get('to', ''), variables)
        subject = substitute_variables(action.get('subject', 'EchoBell Alert'), variables)
        body = substitute_variables(action.get('body', ''), variables)
        
        # Get SMTP config from environment
        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_user = os.getenv('SMTP_USER', '')
        smtp_pass = os.getenv('SMTP_PASS', '')
        from_addr = os.getenv('SMTP_FROM', smtp_user)
        
        if not smtp_user or not smtp_pass:
            logger.warning("SMTP credentials not configured")
            return {
                'action_type': 'email',
                'success': False,
                'error': 'SMTP_USER or SMTP_PASS not configured'
            }
        
        logger.info(f"[EMAIL] To: {to_addr}, Subject: {subject}")
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = from_addr
            msg['To'] = to_addr
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            
            # TODO: Add snapshot attachment if requested
            # if action.get('attach_snapshot'):
            #     with open(snapshot_path, 'rb') as f:
            #         attach = MIMEImage(f.read())
            #         msg.attach(attach)
            
            # Send via SMTP
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            
            return {
                'action_type': 'email',
                'success': True,
                'to': to_addr,
                'subject': subject
            }
            
        except Exception as e:
            logger.error(f"Email action failed: {e}")
            return {
                'action_type': 'email',
                'success': False,
                'error': str(e)
            }
