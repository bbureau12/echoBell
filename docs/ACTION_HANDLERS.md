# Action Handler System

## Overview

EchoBell's policy engine uses a **plugin-based action handler registry** that makes it easy to:

- ✅ Add new action types without modifying core code
- ✅ Keep action logic isolated and testable
- ✅ Share handlers across projects
- ✅ Override built-in handlers with custom implementations

## Architecture

```
Policy Match → ActionExecutor → ActionRegistry → Handler.execute()
                                      ↓
                            [telegram, speak, webhook,
                             sms, email, home_assistant, ...]
```

### Key Components

1. **ActionHandler Protocol** - Interface all handlers must implement
2. **ActionRegistry** - Global registry mapping action types to handler classes
3. **@register_action_handler** - Decorator for automatic registration
4. **ActionExecutor** - Orchestrates handler lookup and execution

---

## Built-in Action Handlers

### 1. Telegram (`telegram`)

Send message via Telegram Bot API.

**Configuration**:
```yaml
actions:
  - type: telegram
    message: "Alert: {vehicle_color} {vehicle_type} detected"
    priority: urgent  # low, normal, urgent
    send_photo: false
    photo_path: "/path/to/snapshot.jpg"  # Optional
```

**Environment Variables**:
- `TELEGRAM_BOT_TOKEN` - Bot token from @BotFather
- `TELEGRAM_CHAT_ID` - Your chat ID
- `TELEGRAM_ENABLED` - Enable/disable (default: true)

**Features**:
- Variable substitution in messages
- Priority levels (affects message formatting)
- Optional photo attachments
- Records to `alert_history` table
- Retry on rate limits (429 errors)

---

### 2. Text-to-Speech (`speak`)

Announce text via TTS system.

**Configuration**:
```yaml
actions:
  - type: speak
    text: "Hello! Please leave the package by the door."
    voice: default  # Voice model to use
```

**Integration**: Calls `packages/tts/piper.py`

---

### 3. Webhook (`webhook`)

HTTP request to external service (Home Assistant, IFTTT, custom APIs).

**Configuration**:
```yaml
actions:
  - type: webhook
    url: "http://homeassistant:8123/api/services/light/turn_on"
    method: POST  # GET, POST, PUT
    timeout: 5.0  # Seconds
    headers:
      Authorization: "Bearer {env.HA_TOKEN}"
    payload:
      entity_id: "light.driveway"
      brightness: 255
      color: "{vehicle_color}"
```

**Features**:
- Variable substitution in URL, headers, payload
- Supports GET, POST, PUT methods
- Configurable timeout
- Response logging (truncated)

---

### 4. Log (`log`)

Simple console logging (useful for debugging).

**Configuration**:
```yaml
actions:
  - type: log
    message: "Policy matched: {policy_id}"
    level: INFO  # DEBUG, INFO, WARNING, ERROR
```

---

## Creating Custom Action Handlers

### Step 1: Create Handler Class

```python
from packages.policy.action_handlers import (
    register_action_handler,
    substitute_variables,
    record_alert_history
)
import sqlite3
from typing import Dict, Any

@register_action_handler("my_custom_action")
class MyCustomActionHandler:
    """Describe what your action does"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(
        self,
        action: Dict[str, Any],
        variables: Dict[str, str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the action"""
        
        # 1. Extract config from action dict
        my_param = action.get('my_param', 'default')
        message = substitute_variables(action.get('message', ''), variables)
        
        # 2. Perform action (API call, database write, etc.)
        try:
            result = do_something(my_param, message)
            
            # 3. Return success result
            return {
                'action_type': 'my_custom_action',
                'success': True,
                'result': result
            }
            
        except Exception as e:
            # 4. Return failure result
            return {
                'action_type': 'my_custom_action',
                'success': False,
                'error': str(e)
            }
```

### Step 2: Import Handler Module

Handlers are auto-registered when imported. Two options:

**Option A: Import in policy module**
```python
# In packages/policy/__init__.py or apply.py
import examples.custom_action_handlers  # Auto-registers all handlers
```

**Option B: Direct import in your code**
```python
# In your application startup
from examples.custom_action_handlers import MyCustomActionHandler
```

### Step 3: Use in Policies

Once registered, use like any built-in action:

```yaml
policies:
  - id: my_policy
    name: "Test Custom Action"
    conditions: {...}
    actions:
      - type: my_custom_action
        my_param: "value"
        message: "Hello {name}!"
```

---

## Helper Functions

### Variable Substitution

```python
from packages.policy.action_handlers import substitute_variables

message = "Hello {name}, you have {count} alerts"
variables = {"name": "Alice", "count": "3"}

result = substitute_variables(message, variables)
# "Hello Alice, you have 3 alerts"
```

**Nested substitution** (for dicts):
```python
from packages.policy.action_handlers import substitute_variables_in_dict

data = {
    "message": "Hello {name}",
    "metadata": {
        "count": "{count}",
        "list": ["item1", "{item2}"]
    }
}
variables = {"name": "Bob", "count": "5", "item2": "value"}

result = substitute_variables_in_dict(data, variables)
# {"message": "Hello Bob", "metadata": {"count": "5", "list": ["item1", "value"]}}
```

### Alert History Recording

```python
from packages.policy.action_handlers import record_alert_history

record_alert_history(
    conn=conn,
    context={
        'camera_id': 1,
        'track_key': 'plate_abc123',
        'track_type': 'vehicle',
        'policy_id': 'loitering_alert'
    },
    alert_type='telegram',
    message='Alert sent!',
    priority='urgent',
    success=True,
    error_message=None
)
```

**Purpose**:
- Spam prevention (check recent alerts via `no_recent_alert` condition)
- Escalation patterns (check if alert sent via `alert_sent_within` condition)
- Audit trail (who was alerted when)

---

## Complete Examples

### Example 1: SMS Handler (Twilio)

```python
@register_action_handler("sms")
class SMSActionHandler:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        from twilio.rest import Client
        import os
        
        to_number = substitute_variables(action['to'], variables)
        message = substitute_variables(action['message'], variables)
        
        client = Client(
            os.getenv('TWILIO_ACCOUNT_SID'),
            os.getenv('TWILIO_AUTH_TOKEN')
        )
        
        client.messages.create(
            to=to_number,
            from_=os.getenv('TWILIO_FROM_NUMBER'),
            body=message
        )
        
        record_alert_history(
            self.conn, context, 'sms', message,
            priority=action.get('priority', 'normal'),
            success=True
        )
        
        return {
            'action_type': 'sms',
            'success': True,
            'to': to_number
        }
```

**Policy usage**:
```yaml
actions:
  - type: sms
    to: "+15551234567"
    message: "⚠️ {vehicle_color} {vehicle_type} at driveway"
    priority: urgent
```

### Example 2: Home Assistant Integration

```python
@register_action_handler("home_assistant")
class HomeAssistantActionHandler:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        import httpx
        import os
        
        entity_id = action['entity_id']
        service = action.get('service', 'turn_on')
        data = substitute_variables_in_dict(action.get('data', {}), variables)
        
        domain = entity_id.split('.')[0]
        url = f"{os.getenv('HA_URL')}/api/services/{domain}/{service}"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={'entity_id': entity_id, **data},
                headers={'Authorization': f"Bearer {os.getenv('HA_TOKEN')}"}
            )
            response.raise_for_status()
        
        return {
            'action_type': 'home_assistant',
            'success': True,
            'entity_id': entity_id
        }
```

**Policy usage**:
```yaml
actions:
  - type: home_assistant
    entity_id: "light.driveway"
    service: "turn_on"
    data:
      brightness: 255
      rgb_color: [255, 0, 0]  # Red for alerts
```

### Example 3: Database Analytics Logger

```python
@register_action_handler("analytics_log")
class AnalyticsLogHandler:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        from datetime import datetime
        
        event_type = action.get('event_type', 'general')
        metadata = substitute_variables_in_dict(
            action.get('metadata', {}),
            variables
        )
        
        self.conn.execute("""
            INSERT INTO analytics_events
            (event_type, camera_id, track_key, metadata, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            event_type,
            context.get('camera_id'),
            context.get('track_key'),
            json.dumps(metadata),
            int(datetime.now().timestamp())
        ))
        self.conn.commit()
        
        return {
            'action_type': 'analytics_log',
            'success': True,
            'event_type': event_type
        }
```

**Policy usage**:
```yaml
actions:
  - type: analytics_log
    event_type: "loitering_detected"
    metadata:
      duration_seconds: "{track_duration_seconds}"
      confidence: "{intent_conf}"
```

---

## Testing Action Handlers

### Unit Testing

```python
import pytest
import sqlite3
from packages.policy.action_handlers import ActionRegistry

@pytest.mark.asyncio
async def test_my_custom_handler():
    # Setup
    conn = sqlite3.connect(":memory:")
    handler = ActionRegistry.get_handler("my_custom_action", conn)
    
    # Execute
    result = await handler.execute(
        action={'my_param': 'test'},
        variables={'name': 'Alice'},
        context={'camera_id': 1, 'track_key': 'test_123'}
    )
    
    # Assert
    assert result['success'] == True
    assert result['action_type'] == 'my_custom_action'
```

### Integration Testing

```python
from packages.policy.apply import evaluate_policies

@pytest.mark.asyncio
async def test_policy_with_custom_action():
    # Import your handler to register it
    import examples.custom_action_handlers
    
    # Create test evidence
    evidence = [
        {'source': 'vision', 'feature': 'vehicle_present', 'value': 'true', 'conf': 0.9}
    ]
    
    # Evaluate policies (will use your custom handler)
    results = await evaluate_policies(
        evidence=evidence,
        context={'camera_id': 1, 'track_key': 'test'},
        conn=conn,
        policy_file='test_policies.yaml'
    )
    
    # Check results
    assert len(results) > 0
    assert results[0]['action_type'] == 'my_custom_action'
```

---

## Best Practices

### 1. Error Handling

Always return success/failure status:

```python
try:
    result = do_action()
    return {'action_type': 'my_action', 'success': True, 'result': result}
except Exception as e:
    logger.error(f"Action failed: {e}")
    return {'action_type': 'my_action', 'success': False, 'error': str(e)}
```

### 2. Logging

Log important events for debugging:

```python
import logging
logger = logging.getLogger(__name__)

async def execute(self, action, variables, context):
    logger.info(f"[MY_ACTION] Executing with params: {action}")
    # ... action logic
    logger.debug(f"[MY_ACTION] Result: {result}")
```

### 3. Configuration Validation

Validate required parameters early:

```python
async def execute(self, action, variables, context):
    required_param = action.get('required_param')
    if not required_param:
        return {
            'action_type': 'my_action',
            'success': False,
            'error': 'Missing required_param'
        }
```

### 4. Environment Variables

Use environment variables for secrets:

```python
import os

api_key = os.getenv('MY_SERVICE_API_KEY')
if not api_key:
    logger.warning("MY_SERVICE_API_KEY not configured")
    return {'success': False, 'error': 'API key not configured'}
```

### 5. Timeouts

Set reasonable timeouts for external calls:

```python
async with httpx.AsyncClient(timeout=5.0) as client:
    response = await client.post(url, ...)
```

### 6. Alert History

Record alerts for spam prevention:

```python
record_alert_history(
    self.conn, context, 'my_alert_type', message,
    priority='normal', success=True
)
```

---

## Advanced Patterns

### Conditional Action Execution

Execute sub-actions based on runtime conditions:

```python
async def execute(self, action, variables, context):
    mode = action.get('mode', 'default')
    
    if mode == 'urgent':
        # Send SMS + Telegram + turn on lights
        await self._send_sms(...)
        await self._send_telegram(...)
        await self._control_lights(...)
    elif mode == 'quiet':
        # Log only
        logger.info("Quiet mode - no alerts")
    
    return {'success': True, 'mode': mode}
```

### Chained Actions

Execute multiple actions sequentially:

```python
async def execute(self, action, variables, context):
    results = []
    
    for sub_action in action.get('actions', []):
        handler = ActionRegistry.get_handler(sub_action['type'], self.conn)
        result = await handler.execute(sub_action, variables, context)
        results.append(result)
    
    return {
        'action_type': 'chain',
        'success': all(r['success'] for r in results),
        'results': results
    }
```

### Rate Limiting

Prevent action spam:

```python
async def execute(self, action, variables, context):
    track_key = context.get('track_key')
    
    # Check if action executed recently
    recent = self.conn.execute("""
        SELECT sent_ts FROM alert_history
        WHERE track_key = ? AND alert_type = 'my_action'
        AND sent_ts > ?
        ORDER BY sent_ts DESC LIMIT 1
    """, (track_key, time.time() - 300)).fetchone()
    
    if recent:
        return {
            'success': False,
            'error': 'Rate limited - action executed recently'
        }
    
    # Execute action
    # ...
```

---

## Troubleshooting

### Handler Not Found

**Error**: `No handler registered for action type: my_action`

**Solution**: Ensure handler module is imported before policy evaluation:
```python
import examples.custom_action_handlers  # Register handlers
from packages.policy.apply import evaluate_policies
```

### Variable Not Substituting

**Error**: Message contains `{variable}` literally

**Solution**: Check variable name spelling and use `substitute_variables()`:
```python
message = substitute_variables(action['message'], variables)
```

### Action Fails Silently

**Check**:
1. Exception caught but not logged?
2. Return status says `success: True` but action didn't execute?
3. Check logs with `DEBUG` level

### Database Connection Issues

Handler receives connection in `__init__`:
```python
def __init__(self, conn: sqlite3.Connection):
    self.conn = conn  # Use this, don't create new connection
```

---

## See Also

- [POLICY_API.md](POLICY_API.md) - REST API for policy management
- [POLICY_REFERENCE.md](POLICY_REFERENCE.md) - Condition operators and examples
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [examples/custom_action_handlers.py](../examples/custom_action_handlers.py) - Example implementations
