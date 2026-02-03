# Echonet Listening Mode - LLM-Requested Voice Conversations

## Overview

The Echonet listening mode integration allows the LLM to request additional voice input from users when it needs more information. Instead of requiring the user to say the wake word again, the LLM can activate "open listening" mode for a natural conversational experience.

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

## Architecture

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

### Components

1. **EchonetModeService** (`echonet_mode_service.py`)
   - `activate_listening()` - PUT /state with mode="open_listen"
   - `deactivate_listening()` - PUT /state with mode="trigger"
   - `get_echonet_state()` - GET /state
   - Uses httpx for async HTTP with API key auth

2. **Services Layer** (`services.py`)
   - `activate_echonet_listening()` - Wrapper for activation
   - `deactivate_echonet_listening()` - Wrapper for deactivation
   - `get_echonet_instances_status()` - Status of all Echonets

3. **MCP Tools** (`mcp_server.py`)
   - `activate_echonet_listening` - Exposed to LLM
   - `deactivate_echonet_listening` - Exposed to LLM
   - `get_echonet_status` - Query instance states

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

## Configuration

### Environment Variables

**Echonet Side** (edge device):
```bash
ECHONET_LISTEN_TIMEOUT=30          # Seconds in open_listen before timeout
ECHONET_WAKE_PHRASES=echobell      # Wake word(s)
ECHONET_TARGET_NAME=echobell       # Target name for state API
```

**Policy Server Side**:
```bash
ECHONET_API_KEY=dontgiveitupluffy  # API key for Echonet state changes
```

### Echonet State API

The Echonet state endpoint is defined in `edge/echonet/server.py`:

```python
@router.put("/state")
async def update_listen_mode(request: ListenModeRequest):
    """
    Update the listening mode.
    
    Modes:
    - trigger: Wait for wake word
    - open_listen: Continuous listening (with timeout)
    - inactive: Completely off
    """
    # Validate X-API-Key header
    # Update _state.listen_mode
    # Return new state
```

## Security & Authorization

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

## Testing

### Manual Testing

```bash
# 1. Start policy server with Echonet discovery
cd central/policy-server
python server.py

# 2. Verify Echonet discovered
curl http://localhost:8002/admin/echonet/status

# 3. Simulate LLM activating listening
curl -X POST http://localhost:8002/test/activate-listening \
  -H "Content-Type: application/json" \
  -d '{"reason": "Testing LLM-requested conversation"}'

# 4. Check Echonet state
curl http://echonet-ip:8123/state
# Should show: "listen_mode": "open_listen"

# 5. Wait for timeout or deactivate
curl -X POST http://localhost:8002/test/deactivate-listening
```

### Integration Test

See `tests/test_echonet_listening.py`:

```python
async def test_llm_activates_listening():
    # Setup: Echonet in trigger mode
    # Action: LLM calls activate_echonet_listening
    # Assert: Echonet mode changes to open_listen
    # Cleanup: Deactivate or wait for timeout
```

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

## Future Enhancements

### Planned Features

1. **Session Awareness**: Link multi-turn via `session_id` in `voice_commands`
2. **Adaptive Timeouts**: Extend timeout if user still speaking
3. **Zone-Aware Activation**: Only activate Echonet in user's current zone
4. **Confidence Decay**: Require higher confidence for extended conversations
5. **Multi-Echonet Dialog**: Coordinate across multiple Echonet instances

### Roadmap Integration

See `docs/ROADMAP.md` section "Voice Interface Enhancements" for:
- Emotion detection during conversations
- Interrupt handling (user says "wait" or "stop")
- Voice-based 2FA for high-security actions
- Speaker diarization for multi-person conversations

## Related Documentation

- `VOICE_COMMAND_SUMMARY.md` - Voice command system overview
- `ECHONET_INTEGRATION.md` - Echonet discovery and registration
- `MCP_SERVER.md` - MCP tool development guide
- `TRUST_FLOW.md` - Voiceprint authorization model
