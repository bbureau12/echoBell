# Action Handler System - Visual Architecture

## Complete Flow Diagram

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

## Handler Registration Flow

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

## Variable Substitution Flow

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

## Example: Telegram Handler Execution

```
┌─────────────────────────────────────────────────────────────────┐
│  POLICY ACTION TRIGGERED                                        │
│  action = {                                                     │
│    "type": "telegram",                                          │
│    "message": "⚠️ {vehicle_color} {vehicle_type} detected",     │
│    "priority": "urgent"                                         │
│  }                                                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  EXECUTOR GETS HANDLER                                          │
│  handler = ActionRegistry.get_handler("telegram", conn)         │
│  # Returns: TelegramActionHandler instance                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  HANDLER EXECUTES                                               │
│  result = await handler.execute(                                │
│      action={...},                                              │
│      variables={"vehicle_color": "red", "vehicle_type": "suv"}, │
│      context={"camera_id": 1, "track_key": "abc123"}            │
│  )                                                              │
│                                                                 │
│  Inside execute():                                              │
│  1. message = "⚠️ red suv detected"  # After substitution       │
│  2. send_telegram(message)           # API call                 │
│  3. record_alert_history(...)        # Spam prevention          │
│  4. return {"success": True, ...}    # Result                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  RESULT RETURNED TO EXECUTOR                                    │
│  {                                                              │
│    "action_type": "telegram",                                   │
│    "success": True,                                             │
│    "message": "⚠️ red suv detected",                            │
│    "priority": "urgent"                                         │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Adding Custom Handler - Step by Step

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: Create Handler File                                    │
│ File: examples/my_handlers.py                                  │
│                                                                 │
│ from packages.policy.action_handlers import (                  │
│     register_action_handler,                                   │
│     substitute_variables                                       │
│ )                                                              │
│                                                                 │
│ @register_action_handler("sms")                                │
│ class SMSActionHandler:                                        │
│     def __init__(self, conn):                                  │
│         self.conn = conn                                       │
│                                                                 │
│     async def execute(self, action, variables, context):       │
│         message = substitute_variables(                        │
│             action['message'],                                 │
│             variables                                          │
│         )                                                      │
│         # Send SMS via Twilio...                               │
│         return {"success": True, "action_type": "sms"}         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: Import Handler (registers automatically)               │
│                                                                 │
│ # In your app startup or policy module                         │
│ import examples.my_handlers  # Registers all handlers in file  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: Use in Policy                                           │
│ File: config/policy_rules.yaml                                 │
│                                                                 │
│ policies:                                                       │
│   - id: test_sms                                                │
│     name: "Test SMS Alert"                                      │
│     conditions: {...}                                           │
│     actions:                                                    │
│       - type: sms            # ← Your custom action!            │
│         to: "+15551234567"                                      │
│         message: "Alert: {vehicle_color} detected"              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: Policy Executes → SMS Sent!                            │
│                                                                 │
│ Evidence matches → Policy triggers → Executor looks up "sms" → │
│ SMSActionHandler.execute() called → SMS sent via Twilio        │
└─────────────────────────────────────────────────────────────────┘
```

## Benefits Visualization

```
┌────────────────────────────────────────────────────────────────┐
│           BEFORE (if/elif chain)                               │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  executor.py (200 lines):                                      │
│  ┌──────────────────────────────────────────┐                 │
│  │ async def execute_actions(...):          │                 │
│  │   if action['type'] == 'telegram':       │                 │
│  │     # 30 lines telegram logic            │                 │
│  │   elif action['type'] == 'speak':        │                 │
│  │     # 20 lines speak logic               │                 │
│  │   elif action['type'] == 'webhook':      │                 │
│  │     # 40 lines webhook logic             │                 │
│  │   elif action['type'] == 'sms':          │  ← EDIT HERE    │
│  │     # 30 lines SMS logic                 │     TO ADD      │
│  │   # ... more elif branches               │                 │
│  └──────────────────────────────────────────┘                 │
│                                                                │
│  ❌ Single file grows indefinitely                             │
│  ❌ Tight coupling                                             │
│  ❌ Hard to test individual actions                            │
│  ❌ Can't reuse across projects                                │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│           AFTER (registry pattern)                             │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  executor.py (30 lines):                                       │
│  ┌──────────────────────────────────────────┐                 │
│  │ async def execute_actions(...):          │                 │
│  │   handler = ActionRegistry.get_handler(  │                 │
│  │     action['type'], conn                 │                 │
│  │   )                                      │                 │
│  │   return await handler.execute(...)      │                 │
│  └──────────────────────────────────────────┘                 │
│                                                                │
│  action_handlers.py:                                           │
│  ┌──────────────────────────────────────────┐                 │
│  │ @register_action_handler("telegram")     │                 │
│  │ class TelegramActionHandler: ...         │                 │
│  │                                          │                 │
│  │ @register_action_handler("speak")        │                 │
│  │ class SpeakActionHandler: ...            │                 │
│  └──────────────────────────────────────────┘                 │
│                                                                │
│  examples/sms_handler.py:                    ← NEW FILE       │
│  ┌──────────────────────────────────────────┐     (no edits   │
│  │ @register_action_handler("sms")          │      to core)   │
│  │ class SMSActionHandler: ...              │                 │
│  └──────────────────────────────────────────┘                 │
│                                                                │
│  ✅ Executor stays simple (30 lines)                           │
│  ✅ Each handler isolated                                      │
│  ✅ Easy to test                                               │
│  ✅ Reusable across projects (just import)                     │
│  ✅ Third-party plugins possible                               │
└────────────────────────────────────────────────────────────────┘
```
