# Action Handler System - Complete Guide

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

### Complete Flow Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                     1. POLICY EVALUATION                           │
│  Evidence + Context → PolicyEvaluator → Matching Policies          │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│                     2. ACTION EXECUTOR                             │
│  For each action in matched policy:                                │
│    ├─ Extract action type (e.g., "telegram")                       │
│    ├─ Lookup handler in registry                                   │
│    └─ Execute handler.execute()                                    │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│                     3. ACTION REGISTRY                             │
│  Global dictionary mapping action types to handler classes:        │
│    {                                                                │
│      "telegram": TelegramActionHandler,                            │
│      "speak": SpeakActionHandler,                                  │
│      "webhook": WebhookActionHandler,                              │
│      "sms": SMSActionHandler,            # Custom handler          │
│      "home_assistant": HAActionHandler   # Custom handler          │
│    }                                                                │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│                     4. HANDLER INSTANTIATION                       │
│  handler_class(conn) → handler instance                            │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│                     5. HANDLER EXECUTION                           │
│  await handler.execute(action, variables, context)                 │
│    ├─ Substitute {variables} in action config                      │
│    ├─ Perform action (API call, database write, etc.)              │
│    ├─ Record to alert_history (if applicable)                      │
│    └─ Return {"success": bool, ...}                                │
└────────────────────────────────────────────────────────────────────┘
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

### Quick Start

**Step 1**: Create handler class

```python
# examples/custom_action_handlers.py

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
            result = self._do_action(my_param, message)
            
            # 3. Optional: Record to alert history
            record_alert_history(
                conn=self.conn,
                camera_id=context.get('camera_id'),
                track_key=context.get('track_key'),
                action_type='my_custom_action',
                message=message,
                priority='normal'
            )
            
            return {
                "success": True,
                "action_type": "my_custom_action",
                "result": result
            }
            
        except Exception as e:
            return {
                "success": False,
                "action_type": "my_custom_action",
                "error": str(e)
            }
    
    def _do_action(self, param, message):
        # Your custom logic here
        pass
```

**Step 2**: Import handler at startup

```python
# In your policy server or agent startup code
import examples.custom_action_handlers  # Triggers @register_action_handler

# Handler is now available!
```

### Handler Registration Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  1. DEFINE HANDLER CLASS                                        │
│                                                                 │
│  @register_action_handler("sms")                                │
│  class SMSActionHandler:                                        │
│      def __init__(self, conn):                                  │
│          self.conn = conn                                       │
│                                                                 │
│      async def execute(self, action, variables, context):       │
│          # Send SMS logic here                                  │
│          return {"success": True, "action_type": "sms"}         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. DECORATOR EXECUTES (at import time)                         │
│                                                                 │
│  ActionRegistry.register("sms", SMSActionHandler)               │
│    ↓                                                            │
│  ActionRegistry._handlers["sms"] = SMSActionHandler             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. HANDLER NOW AVAILABLE                                       │
│                                                                 │
│  ActionRegistry.list_handlers()                                 │
│  # Returns: ['telegram', 'speak', 'webhook', 'sms']             │
│                                                                 │
│  handler = ActionRegistry.get_handler("sms", conn)              │
│  # Returns: SMSActionHandler instance                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Variable Substitution

All handlers have access to `substitute_variables()` for dynamic content.

```
┌─────────────────────────────────────────────────────────────────┐
│  ACTION CONFIG (from policy)                                    │
│  {                                                              │
│    "type": "telegram",                                          │
│    "message": "Alert: {vehicle_color} {vehicle_type}"           │
│  }                                                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  VARIABLES (from evidence/context)                              │
│  {                                                              │
│    "vehicle_color": "white",                                    │
│    "vehicle_type": "sedan"                                      │
│  }                                                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  HANDLER SUBSTITUTES                                            │
│  message = substitute_variables(                                │
│      "Alert: {vehicle_color} {vehicle_type}",                   │
│      {"vehicle_color": "white", "vehicle_type": "sedan"}        │
│  )                                                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  FINAL MESSAGE                                                  │
│  "Alert: white sedan"                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Example: Complete Custom Handler

```python
# examples/custom_action_handlers.py

from packages.policy.action_handlers import register_action_handler, substitute_variables
import requests
import os

@register_action_handler("home_assistant")
class HomeAssistantActionHandler:
    """Call Home Assistant services (lights, automation, etc.)"""
    
    def __init__(self, conn):
        self.conn = conn
        self.ha_url = os.getenv("HA_URL", "http://homeassistant:8123")
        self.ha_token = os.getenv("HA_TOKEN")
    
    async def execute(self, action, variables, context):
        # Extract config
        service = action.get('service')  # e.g., "light.turn_on"
        entity_id = substitute_variables(action.get('entity_id', ''), variables)
        params = action.get('params', {})
        
        # Substitute variables in params
        for key, value in params.items():
            if isinstance(value, str):
                params[key] = substitute_variables(value, variables)
        
        # Call Home Assistant API
        url = f"{self.ha_url}/api/services/{service}"
        headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "entity_id": entity_id,
            **params
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            response.raise_for_status()
            
            return {
                "success": True,
                "action_type": "home_assistant",
                "service": service,
                "entity_id": entity_id
            }
        except Exception as e:
            return {
                "success": False,
                "action_type": "home_assistant",
                "error": str(e)
            }
```

**Usage in policy**:
```yaml
actions:
  - type: home_assistant
    service: light.turn_on
    entity_id: light.driveway
    params:
      brightness: 255
      color_name: "{vehicle_color}"  # Dynamic!
```

---

## Testing Custom Handlers

```python
# tests/test_custom_handlers.py

import sqlite3
import pytest
from examples.custom_action_handlers import HomeAssistantActionHandler

@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()

@pytest.mark.asyncio
async def test_home_assistant_handler(conn):
    handler = HomeAssistantActionHandler(conn)
    
    action = {
        "service": "light.turn_on",
        "entity_id": "light.driveway",
        "params": {"brightness": 255}
    }
    
    variables = {}
    context = {"camera_id": 1}
    
    result = await handler.execute(action, variables, context)
    
    assert result["success"] == True
    assert result["action_type"] == "home_assistant"
```

---

## Best Practices

1. **Always return a result dict** with `success` and `action_type` keys
2. **Use substitute_variables()** for any user-facing text
3. **Handle exceptions gracefully** and return error details
4. **Use environment variables** for credentials/config
5. **Write unit tests** for your handlers
6. **Document required config fields** in docstring
7. **Log important operations** for debugging

---

## See Also

- [POLICY_REFERENCE.md](../POLICY_REFERENCE.md) - Policy configuration guide
- [examples/custom_action_handlers.py](../../examples/custom_action_handlers.py) - Working examples
- [tests/test_action_handlers.py](../../tests/test_action_handlers.py) - Handler tests
