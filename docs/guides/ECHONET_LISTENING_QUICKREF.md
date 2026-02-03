# Echonet Listening Mode - Quick Reference

## LLM Tools

### activate_echonet_listening
**When to use**: LLM needs more information from user

**Arguments**:
- `echonet_url` (optional) - Auto-detected if omitted
- `target_name` (optional) - Default: "echobell"  
- `reason` (optional) - Why you're activating

**Example**:
```json
{
  "name": "activate_echonet_listening",
  "arguments": {
    "reason": "Need clarification on which door"
  }
}
```

### deactivate_echonet_listening
**When to use**: Conversation complete

**Arguments**: Same as activate

### get_echonet_status
**When to use**: Check Echonet states

**Returns**: List of instances with current modes

## Code Usage

### From Services Layer
```python
from services import activate_echonet_listening, deactivate_echonet_listening

# Activate
result = await activate_echonet_listening(
    echonet_url="http://192.168.1.50:8123",
    target_name="echobell",
    source="llm",
    reason="Need more info"
)

# Deactivate
result = await deactivate_echonet_listening(
    echonet_url="http://192.168.1.50:8123",
    target_name="echobell",
    source="llm",
    reason="Done"
)
```

### Direct Service Access
```python
from echonet_mode_service import get_echonet_mode_service

service = get_echonet_mode_service()

# Activate
await service.activate_listening(
    echonet_url="http://192.168.1.50:8123",
    target_name="echobell",
    source="test",
    reason="Testing"
)

# Get state
state = await service.get_echonet_state("http://192.168.1.50:8123")
print(state['listen_mode'])  # 'trigger', 'open_listen', or 'inactive'
```

## Environment Setup

```bash
# Required
export ECHONET_API_KEY=dontgiveitupluffy

# Optional (Echonet side)
export ECHONET_LISTEN_TIMEOUT=30  # seconds
export ECHONET_TARGET_NAME=echobell
```

## Testing

```bash
# Quick test
python tests/test_echonet_listening.py \
  --echonet-url http://192.168.1.50:8123

# With timeout test (takes 35s)
python tests/test_echonet_listening.py \
  --echonet-url http://192.168.1.50:8123 \
  --test-timeout
```

## Troubleshooting

### Mode not changing
```bash
# Check Echonet registered
curl http://localhost:8002/admin/echonet/status

# Check API key matches
echo $ECHONET_API_KEY

# Verify Echonet state
curl http://192.168.1.50:8123/state
```

### Stuck in open_listen
```bash
# Force return to trigger
curl -X PUT http://192.168.1.50:8123/state \
  -H "X-API-Key: $ECHONET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"target_name":"echobell","mode":"trigger","source":"manual","reason":"Force reset"}'
```

## Conversation Flow Examples

### Clarification Needed
```
User: "Unlock the door"
LLM: activate_echonet_listening(reason="Ambiguous door")
LLM: "Which door - front, back, or garage?"
User: "Front door"
LLM: [Process unlock]
LLM: deactivate_echonet_listening(reason="Got clarification")
```

### Confirmation Required
```
User: "Disable security"
LLM: activate_echonet_listening(reason="Security action confirmation")
LLM: "This will disable all cameras. Confirm?"
User: "Yes, confirmed"
LLM: [Execute if voiceprint high confidence]
LLM: deactivate_echonet_listening(reason="Confirmed")
```

### Multi-Step
```
User: "Create schedule"
LLM: activate_echonet_listening(reason="Multi-step creation")
LLM: "What should happen?"
User: "Lock doors at 10pm"
LLM: "Which days?"
User: "Weekdays"
LLM: [Create schedule]
LLM: deactivate_echonet_listening(reason="Schedule created")
```

## Database Queries

### Recent activations
```sql
SELECT 
  correlation_id,
  text,
  actions_taken,
  timestamp
FROM voice_commands
WHERE actions_taken LIKE '%activate_echonet_listening%'
ORDER BY timestamp DESC
LIMIT 10;
```

### Activation success rate
```sql
SELECT 
  COUNT(*) as total_activations,
  SUM(CASE WHEN auth_result = 'allowed' THEN 1 ELSE 0 END) as successful,
  AVG(processing_time_ms) as avg_time_ms
FROM voice_commands
WHERE actions_taken LIKE '%activate_echonet_listening%';
```

## Permissions

Tool permissions (from `mcp_tool_permissions` table):
```
activate_echonet_listening   | voice_enabled=1 | confidence>=0.75 | level=normal
deactivate_echonet_listening | voice_enabled=1 | confidence>=0.75 | level=normal
get_echonet_status           | voice_enabled=1 | confidence>=0.75 | level=low
```

## Files Reference

- Service: `central/policy-server/echonet_mode_service.py`
- Integration: `central/policy-server/services.py`
- MCP Tools: `central/policy-server/mcp_server.py`
- Migration: `infra/db/migrations/015_add_voice_commands.sql`
- Test: `tests/test_echonet_listening.py`
- Docs: `docs/ECHONET_LISTENING_MODE.md`
