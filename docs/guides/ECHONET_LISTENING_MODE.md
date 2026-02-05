# Echonet Listening Mode

> **Quick Reference**: Jump to [Quick Start](#quick-start) | [MCP Tools](#mcp-tool-usage) | [Code Examples](#code-usage)

## Overview

The Echonet listening mode integration allows the LLM to request additional voice input from users when it needs more information. Instead of requiring the user to say the wake word again, the LLM can activate "open listening" mode for a natural conversational experience.

**Implemented**: January 2025 | **Status**: ✅ Complete and tested

---

## Quick Start

### TL;DR

LLM can activate "open listening" mode on Echonet devices for multi-turn conversations without requiring users to repeat the wake word.

### Common Flows

**Clarification Needed**:
```
User: "Unlock the door"
LLM: activate_echonet_listening(reason="Ambiguous door")
LLM: "Which door - front, back, or garage?"
User: "Front door"
LLM: [Process unlock]
LLM: deactivate_echonet_listening(reason="Got clarification")
```

**Confirmation Required**:
```
User: "Disable security"
LLM: activate_echonet_listening(reason="Security action confirmation")
LLM: "This will disable all cameras. Confirm?"
User: "Yes, confirmed"
LLM: [Execute if voiceprint high confidence]
LLM: deactivate_echonet_listening(reason="Confirmed")
```

**Multi-Step Interaction**:
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

---

## Architecture

## How It Works

### Normal Flow (Trigger Mode)
1. User says wake word: "Hey Echobell, what's the status?"
2. Echonet processes command → sends to Policy Server
3. LLM receives partial/ambiguous command
4. **Problem**: User must say wake word again to provide more info

### Enhanced Flow (Open Listening)
1. User says wake word: "Hey Echobell, what's the status?"
2. Echonet processes → Policy Server → LLM
3. LLM recognizes need for clarification
4. **LLM activates listening mode** via MCP tool
5. Echonet enters `open_listen` mode (30s default)
6. User can speak naturally: "The front door status"
7. Echonet sends additional voice → LLM processes complete request
8. LLM deactivates listening or timeout occurs

### State Transitions

**Echonet Listen Modes**:
1. **trigger**: Default mode, requires wake word
2. **open_listen**: Continuous listening (30s timeout)
3. **inactive**: Microphone completely off

**Transition Flow**:
```
trigger ──[LLM activates]──► open_listen ──[timeout/deactivate]──► trigger
   ▲                                                                    │
   └────────────────────────────────────────────────────────────────────┘
```

```
┌─────────────┐         ┌──────────────┐         ┌─────────┐
│   Echonet   │────────▶│ Policy Server│────────▶│   LLM   │
│  (Edge Dev) │         │  (FastAPI)   │         │  (MCP)  │
└─────────────┘         └──────────────┘         └─────────┘
       ▲                        │                       │
       │                        │                       │
       │      PUT /state        │   activate_echonet_   │
       │   mode=open_listen     │      listening()      │
       └────────────────────────┴───────────────────────┘
```

---

## Implementation Components

### Files Created

1. **Core Service Layer** - `central/policy-server/echonet_mode_service.py`
   - `EchonetModeService` class
   - `activate_listening()` - PUT /state with mode="open_listen"
   - `deactivate_listening()` - PUT /state with mode="trigger"
   - `get_echonet_state()` - GET /state
   - Uses httpx for async HTTP with API key auth

2. **Documentation** - `docs/guides/ECHONET_LISTENING_MODE.md`
   - Comprehensive guide (this file)
   - Architecture diagrams
   - MCP tool usage examples
   - Troubleshooting guide

3. **Testing** - `tests/test_echonet_listening.py`
   - Manual verification script
   - Activation/deactivation flow test
   - Timeout behavior test

### Files Modified

1. **Services Layer** - `central/policy-server/services.py`
   - `activate_echonet_listening()` - Wrapper for activation
   - `deactivate_echonet_listening()` - Wrapper for deactivation
   - `get_echonet_instances_status()` - Status of all Echonets

2. **MCP Server** - `central/policy-server/mcp_server.py`
   - Added 3 new MCP tools to TOOLS list:
     - `activate_echonet_listening` - LLM can request voice input
     - `deactivate_echonet_listening` - LLM can end conversation
     - `get_echonet_status` - Query Echonet instance states
   - Added corresponding tool handlers
   - Registered in `TOOL_HANDLERS` dictionary

3. **Database Migration** - `infra/db/migrations/015_add_voice_commands.sql`
   - Added tool permissions for Echonet tools:
     - `activate_echonet_listening`: voice_enabled=1, confidence=0.75, level=normal
     - `deactivate_echonet_listening`: voice_enabled=1, confidence=0.75, level=normal
     - `get_echonet_status`: voice_enabled=1, confidence=0.75, level=low

---

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

---

## MCP Tool Usage

### activate_echonet_listening

**Description**: Activate open listening mode to enable conversation without wake word.

**Parameters**:
- `echonet_url` (optional): Base URL of Echonet instance
  - If not provided, uses first discovered Echonet
- `target_name` (optional): Target name (default: "echobell")
- `reason` (optional): Human-readable reason for logging

**Example**:
```json
{
  "name": "activate_echonet_listening",
  "arguments": {
    "reason": "Need clarification on which door to unlock"
  }
}
```

**Response**:
```json
{
  "success": true,
  "message": "Echonet listening activated",
  "echonet_url": "http://192.168.1.50:8123",
  "previous_mode": "trigger",
  "new_mode": "open_listen"
}
```

### deactivate_echonet_listening

**Description**: End conversation and return to trigger mode.

**Parameters**:
- `echonet_url` (optional): Echonet instance URL
- `target_name` (optional): Target name (default: "echobell")
- `reason` (optional): Reason for ending

**Example**:
```json
{
  "name": "deactivate_echonet_listening",
  "arguments": {
    "reason": "Conversation complete"
  }
}
```

### get_echonet_status

**Description**: Get status of all discovered Echonet instances.

**Response**:
```json
{
  "count": 2,
  "instances": [
    {
      "name": "Front Door Echonet",
      "url": "http://192.168.1.50:8123",
      "zone": "entrance",
      "subzone": "front",
      "current_mode": "trigger",
      "registered": true
    },
    {
      "name": "Kitchen Echonet",
      "url": "http://192.168.1.51:8123",
      "zone": "living",
      "subzone": "kitchen",
      "current_mode": "open_listen",
      "registered": true
    }
  ]
}
```

## Use Cases

### 1. Ambiguous Commands

**Scenario**: User provides insufficient information
```
User: "Unlock the door"
LLM: (Multiple doors exist)
Action: Activate listening
Response: "Which door would you like to unlock?"
User: "The front door"
LLM: Processes complete request
```

### 2. Confirmation Needed

**Scenario**: High-security action requires verification
```
User: "Disable the security system"
LLM: (Security action detected)
Action: Activate listening
Response: "This will disable all cameras. Are you sure?"
User: "Yes, I'm sure"
LLM: Proceeds with action
```

### 3. Multi-Step Interactions

**Scenario**: Complex operation requiring multiple inputs
```
User: "Create a new schedule"
LLM: Activate listening
Response: "What should the schedule do?"
User: "Lock all doors at 10pm"
LLM: (Still listening)
Response: "Which days?"
User: "Monday through Friday"
LLM: Deactivate listening, create schedule
```

### 4. Context Gathering

**Scenario**: LLM needs environmental context
```
User: "Someone's at the door"
LLM: Activate listening
Response: "Do you want me to see who it is?"
User: "Yes, and turn on the porch light"
LLM: Processes both requests
```

---

## Configuration & Permissions

### Environment Variables

**Policy Server**:
```bash
ECHONET_API_KEY=dontgiveitupluffy  # Must match Echonet
```

**Echonet Edge Device**:
```bash
ECHONET_LISTEN_TIMEOUT=30          # Seconds before auto-return to trigger
ECHONET_WAKE_PHRASES=echobell      # Wake word(s)
ECHONET_TARGET_NAME=echobell       # Target name for state API
```

### Tool Permissions

Defined in `mcp_tool_permissions` table:

| Tool                        | Voice Enabled | Min Confidence | Security Level |
|-----------------------------|---------------|----------------|----------------|
| activate_echonet_listening  | Yes           | 0.75           | normal         |
| deactivate_echonet_listening| Yes           | 0.75           | normal         |
| get_echonet_status          | Yes           | 0.75           | low            |

### Authorization Flow

1. Voice command arrives with voiceprint confidence
2. Middleware extracts correlation ID
3. Service layer checks `mcp_tool_permissions`
4. If confidence >= 0.75, LLM can activate listening
5. Activation logged in `voice_commands` table

### Timeout Behavior

- Echonet automatically returns to `trigger` mode after timeout (default 30s)
- LLM can explicitly deactivate earlier
- Timeout prevents stuck-open microphones
- Configurable per Echonet instance

---

## Testing

### Quick Test
```bash
# Set API key
export ECHONET_API_KEY=dontgiveitupluffy

# Run test script
cd tests
python test_echonet_listening.py \
  --echonet-url http://192.168.1.50:8123 \
  --target-name echobell \
  --test-timeout

# Expected output:
# ✓ Successfully activated open_listen mode
# ✓ Successfully deactivated back to trigger mode
# ✓ Echonet auto-returned to trigger mode after timeout
```

### Integration Verification

1. **Start policy server**:
   ```bash
   cd central/policy-server
   python server.py
   ```

2. **Verify Echonet discovered**:
   ```bash
   curl http://localhost:8002/admin/echonet/status
   ```

3. **Test LLM activation** (via MCP client):
   ```
   Human: "Can you check the Echonet status?"
   LLM: [Calls get_echonet_status tool]
   
   Human: "Activate listening mode to ask me a question"
   LLM: [Calls activate_echonet_listening tool]
   ```

4. **Verify mode change**:
   ```bash
   curl http://192.168.1.50:8123/state
   # Should show: "listen_mode": "open_listen"
   ```

### Database Queries

**Recent activations**:
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

**Activation success rate**:
```sql
SELECT 
  COUNT(*) as total_activations,
  SUM(CASE WHEN auth_result = 'allowed' THEN 1 ELSE 0 END) as successful,
  AVG(processing_time_ms) as avg_time_ms
FROM voice_commands
WHERE actions_taken LIKE '%activate_echonet_listening%';
```

---

## Troubleshooting

### Listening Mode Not Activating

**Symptom**: LLM calls `activate_echonet_listening` but mode doesn't change

**Checks**:
1. Verify Echonet discovered: `GET /admin/echonet/status`
2. Check API key matches: `ECHONET_API_KEY` env var
3. Inspect logs for HTTP errors
4. Confirm network connectivity to Echonet URL

**Fix**:
```bash
# Check Echonet registration
curl http://localhost:8002/admin/echonet/status

# Manually re-register
curl -X POST http://localhost:8002/admin/echonet/register \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.50:8123"}'
```

### Mode Stuck in open_listen

**Symptom**: Echonet doesn't return to trigger mode

**Checks**:
1. Verify timeout configured on Echonet side
2. Check if deactivate failed (network issue)
3. Inspect Echonet logs for state transitions

**Fix**:
```bash
# Force deactivate via Echonet API
curl -X PUT http://echonet-ip:8123/state \
  -H "X-API-Key: dontgiveitupluffy" \
  -H "Content-Type: application/json" \
  -d '{
    "target_name": "echobell",
    "mode": "trigger",
    "source": "manual_override",
    "reason": "Forcing return to trigger mode"
  }'
```

### LLM Not Using Tool

**Symptom**: LLM doesn't activate listening when it should

**Checks**:
1. Verify tool registered in MCP server TOOLS list
2. Check tool permissions in database
3. Confirm voiceprint confidence meets threshold
4. Review LLM context window (tool may be truncated)

**Fix**:
```sql
-- Verify tool permission exists
SELECT * FROM mcp_tool_permissions 
WHERE tool_name = 'activate_echonet_listening';

-- Lower confidence threshold if needed
UPDATE mcp_tool_permissions 
SET requires_confidence = 0.70 
WHERE tool_name = 'activate_echonet_listening';
```

## Best Practices

### When to Activate Listening

**Do**:
- User provides ambiguous/incomplete information
- Multi-turn conversation needed
- Confirmation required for security actions
- Complex operations requiring multiple inputs

**Don't**:
- For simple, complete commands
- When information can be inferred from context
- During quiet hours (check `is_quiet_time` first)
- If user explicitly said "never mind"

### Conversation Management

```python
# Example LLM flow
if user_command_ambiguous():
    activate_listening(reason="Need clarification")
    ask_followup_question()
    wait_for_response()
    process_complete_request()
    deactivate_listening(reason="Got sufficient info")
```

### Timeout Handling

```python
# Always set reasonable timeouts
result = await activate_listening(
    reason="Gathering additional details"
)

# Echonet will auto-timeout, but explicitly deactivate when done
if got_all_needed_info():
    await deactivate_listening(reason="Conversation complete")
```

---

## Known Limitations & Future Enhancements

### Current Limitations

1. **No Session Tracking**: No link between activate/deactivate calls
   - Future: Use `session_id` in `voice_commands` table

2. **Single Echonet Auto-Selection**: When URL not provided, uses first discovered
   - Future: Zone-aware selection based on user location

3. **Fixed Timeout**: 30s timeout configured on Echonet side
   - Future: Dynamic timeout based on conversation complexity

4. **No Interrupt Handling**: User can't interrupt LLM during question
   - Future: Support "wait", "stop", "never mind" interrupts

### Roadmap

**Q1 2026**:
- [ ] Session tracking for multi-turn conversations
- [ ] Adaptive timeouts (extend if user still speaking)
- [ ] Zone-aware Echonet selection

**Q2 2026**:
- [ ] Emotion detection during conversations
- [ ] Speaker diarization for multi-person dialogs
- [ ] Interrupt handling (stop/wait/cancel commands)
- [ ] Multi-Echonet coordination (follow user room-to-room)

**Q3 2026**:
- [ ] Voice-based 2FA integration for security actions
- [ ] Confidence decay for extended conversations
- [ ] Context-aware timeout adjustment

---

## Related Documentation

- `VOICE_COMMAND_SUMMARY.md` - Voice command system overview
- `ECHONET_INTEGRATION.md` - Echonet discovery and registration
- `MCP_SERVER.md` - MCP tool development guide
- `TRUST_FLOW.md` - Voiceprint authorization model

