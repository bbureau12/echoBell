# Action Handler Wiring Summary

## Overview

The EchoBell policy engine now uses a **plugin-based action handler registry** that provides:

✅ **Extensible** - Add new action types without modifying core code  
✅ **Decoupled** - Action logic isolated in handler classes  
✅ **Type-safe** - Protocol-based interface ensures consistency  
✅ **Testable** - Handlers can be unit tested independently  
✅ **Auto-discovery** - Handlers auto-register via decorator  

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Policy Evaluation                          │
│  (Evidence matches conditions → Actions executed)               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │  ActionExecutor  │
                  │   (executor.py)  │
                  └────────┬─────────┘
                           │
                           │ Lookup action type
                           ▼
                  ┌──────────────────┐
                  │ ActionRegistry   │
                  │  (global dict)   │
                  └────────┬─────────┘
                           │
              ┌────────────┼────────────┬──────────────┐
              │            │            │              │
              ▼            ▼            ▼              ▼
        ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐
        │Telegram │  │  Speak  │  │ Webhook │  │  Custom  │
        │ Handler │  │ Handler │  │ Handler │  │ Handlers │
        └─────────┘  └─────────┘  └─────────┘  └──────────┘
```

---

## Key Components

### 1. Action Handler Protocol

**File**: `packages/policy/action_handlers.py`

All handlers implement this interface:

```python
class ActionHandler(Protocol):
    def __init__(self, conn: sqlite3.Connection):
        ...
    
    async def execute(
        self,
        action: Dict[str, Any],      # Config from policy YAML/JSON
        variables: Dict[str, str],   # Resolved variable values
        context: Dict[str, Any]      # Runtime context (camera_id, track_key, etc.)
    ) -> Dict[str, Any]:             # Returns {"success": bool, "action_type": str, ...}
        ...
```

### 2. Action Registry

**Pattern**: Global registry pattern

```python
class ActionRegistry:
    _handlers: Dict[str, type] = {}  # action_type -> handler_class
    
    @classmethod
    def register(cls, action_type: str, handler_class: type):
        """Register a handler"""
    
    @classmethod
    def get_handler(cls, action_type: str, conn) -> ActionHandler:
        """Get handler instance"""
    
    @classmethod
    def list_handlers(cls) -> list[str]:
        """List all registered action types"""
```

### 3. Registration Decorator

**Usage**: Decorate handler class to auto-register

```python
@register_action_handler("my_action")
class MyActionHandler:
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        return {"success": True, "action_type": "my_action"}
```

### 4. Action Executor

**File**: `packages/policy/executor.py`

Orchestrates handler lookup and execution:

```python
class ActionExecutor:
    async def execute_actions(self, actions, variables, context):
        for action in actions:
            handler = ActionRegistry.get_handler(action['type'], self.conn)
            if handler:
                result = await handler.execute(action, variables, context)
            # ...
```

---

## Built-in Handlers

| Action Type | Description | File |
|------------|-------------|------|
| `telegram` | Send Telegram message | `action_handlers.py` |
| `speak` | Text-to-speech announcement | `action_handlers.py` |
| `webhook` | HTTP request to external service | `action_handlers.py` |
| `log` | Console logging (debug) | `action_handlers.py` |

---

## Creating Custom Handlers

### Quick Start

**Step 1**: Create handler class

```python
# examples/custom_action_handlers.py

from packages.policy.action_handlers import register_action_handler, substitute_variables
import sqlite3

@register_action_handler("sms")
class SMSActionHandler:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        from twilio.rest import Client
        import os
        
        to = substitute_variables(action['to'], variables)
        message = substitute_variables(action['message'], variables)
        
        client = Client(os.getenv('TWILIO_SID'), os.getenv('TWILIO_TOKEN'))
        client.messages.create(to=to, from_=os.getenv('TWILIO_FROM'), body=message)
        
        return {'action_type': 'sms', 'success': True, 'to': to}
```

**Step 2**: Import to register

```python
# In your app startup or policy module
import examples.custom_action_handlers  # Auto-registers handlers
```

**Step 3**: Use in policies

```yaml
actions:
  - type: sms
    to: "+15551234567"
    message: "Alert: {vehicle_color} {vehicle_type} detected"
```

### Helper Functions

**Variable substitution**:
```python
from packages.policy.action_handlers import substitute_variables

message = substitute_variables("Hello {name}!", {"name": "World"})
# "Hello World!"
```

**Alert history** (for spam prevention):
```python
from packages.policy.action_handlers import record_alert_history

record_alert_history(
    conn, context, 'telegram', 'Alert message',
    priority='urgent', success=True
)
```

---

## Example Handlers

### Home Assistant Integration

```python
@register_action_handler("home_assistant")
class HomeAssistantActionHandler:
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        import httpx, os
        
        entity_id = action['entity_id']
        service = action.get('service', 'turn_on')
        
        url = f"{os.getenv('HA_URL')}/api/services/{entity_id.split('.')[0]}/{service}"
        
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                json={'entity_id': entity_id, **action.get('data', {})},
                headers={'Authorization': f"Bearer {os.getenv('HA_TOKEN')}"}
            )
        
        return {'success': True, 'action_type': 'home_assistant'}
```

**Policy usage**:
```yaml
actions:
  - type: home_assistant
    entity_id: "light.driveway"
    service: "turn_on"
    data:
      brightness: 255
```

### Database Analytics Logger

```python
@register_action_handler("analytics_log")
class AnalyticsLogHandler:
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        import json
        from datetime import datetime
        
        self.conn.execute("""
            INSERT INTO analytics_events (event_type, metadata, timestamp)
            VALUES (?, ?, ?)
        """, (
            action['event_type'],
            json.dumps(substitute_variables_in_dict(action.get('metadata', {}), variables)),
            int(datetime.now().timestamp())
        ))
        self.conn.commit()
        
        return {'success': True, 'action_type': 'analytics_log'}
```

---

## Testing

### Unit Test

```python
import pytest
from packages.policy.action_handlers import ActionRegistry

@pytest.mark.asyncio
async def test_my_handler():
    conn = sqlite3.connect(":memory:")
    handler = ActionRegistry.get_handler("my_action", conn)
    
    result = await handler.execute(
        action={'param': 'value'},
        variables={'name': 'Alice'},
        context={'camera_id': 1}
    )
    
    assert result['success'] == True
```

### Integration Test

```python
from packages.policy.apply import evaluate_policies
import examples.custom_action_handlers  # Register handlers

@pytest.mark.asyncio
async def test_policy_with_custom_action():
    evidence = [{'source': 'vision', 'feature': 'vehicle_present', 'value': 'true', 'conf': 0.9}]
    
    results = await evaluate_policies(
        evidence=evidence,
        context={'camera_id': 1, 'track_key': 'test'},
        conn=conn
    )
    
    assert any(r['action_type'] == 'my_action' for r in results)
```

---

## Benefits Over Previous Approach

### Before (if/elif chain):

```python
async def execute_actions(self, actions, variables, context):
    for action in actions:
        if action['type'] == 'telegram':
            # 30 lines of telegram logic
        elif action['type'] == 'speak':
            # 20 lines of speak logic
        elif action['type'] == 'webhook':
            # 40 lines of webhook logic
        # Adding new action requires editing this file!
```

**Problems**:
- ❌ Single file grows indefinitely
- ❌ Tight coupling to executor
- ❌ Hard to test individual actions
- ❌ Can't override built-in actions
- ❌ No code reuse across projects

### After (registry pattern):

```python
async def execute_actions(self, actions, variables, context):
    for action in actions:
        handler = ActionRegistry.get_handler(action['type'], self.conn)
        if handler:
            result = await handler.execute(action, variables, context)
```

**Advantages**:
- ✅ Executor stays simple (~30 lines)
- ✅ Each handler is isolated class
- ✅ Easy to unit test
- ✅ Can override: re-register same action_type
- ✅ Share handlers via imports
- ✅ Third-party plugins possible

---

## Migration Path

### Existing Policies (No Changes Needed!)

All existing policies work without modification:

```yaml
# This still works exactly the same
actions:
  - type: telegram
    message: "Alert!"
  - type: speak
    text: "Hello!"
```

The only difference is **where** the telegram/speak logic lives:
- **Before**: In `executor.py` methods
- **After**: In `TelegramActionHandler` class

### Adding New Actions

**Before**: Edit `executor.py`, add new elif branch

**After**: Create new file `my_handlers.py`:
```python
from packages.policy.action_handlers import register_action_handler

@register_action_handler("my_new_action")
class MyNewActionHandler:
    # Implementation here
```

Import it: `import my_handlers` → Done!

---

## Files Changed

| File | Change | Purpose |
|------|--------|---------|
| `packages/policy/action_handlers.py` | **NEW** | Registry, protocol, built-in handlers |
| `packages/policy/executor.py` | **REFACTORED** | Now uses registry (30 lines vs 200) |
| `examples/custom_action_handlers.py` | **NEW** | Example custom handlers (SMS, email, etc.) |
| `tests/test_action_handlers.py` | **NEW** | Test suite (8 tests, all passing) |
| `docs/ACTION_HANDLERS.md` | **NEW** | Complete documentation |

---

## Quick Reference

### List Available Actions

```python
from packages.policy.executor import ActionExecutor

executor = ActionExecutor(conn)
print(executor.list_available_actions())
# ['telegram', 'speak', 'webhook', 'log', ...]
```

### Variable Substitution

```python
from packages.policy.action_handlers import substitute_variables

substitute_variables("Hello {name}!", {"name": "Alice"})
# "Hello Alice!"
```

### Custom Handler Template

```python
from packages.policy.action_handlers import register_action_handler

@register_action_handler("my_action")
class MyActionHandler:
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        # Your logic here
        return {'success': True, 'action_type': 'my_action'}
```

---

## See Also

- [ACTION_HANDLERS.md](ACTION_HANDLERS.md) - Complete documentation with examples
- [POLICY_REFERENCE.md](POLICY_REFERENCE.md) - Condition operators and policy syntax
- [POLICY_API.md](POLICY_API.md) - REST API for dynamic policy management
- [examples/custom_action_handlers.py](../examples/custom_action_handlers.py) - Working examples

---

**Status**: ✅ Complete and tested (8/8 tests passing)
