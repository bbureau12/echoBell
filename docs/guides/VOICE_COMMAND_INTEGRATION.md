# Voice Command Integration Implementation

## Overview

This implementation adds voice command support to the EchoBell policy server, enabling it to receive and process voice events from Echonet edge devices. The system maintains correlation tracking, maps voiceprints to trusted persons, enforces authorization policies, and routes commands to the LLM when needed.

## Architecture

```
Echonet Edge Device
    ↓ (POST /voice/listen with voiceprint_user_id)
Policy Server (/voice/listen endpoint)
    ↓
1. Map voiceprint_user_id → trusted_person_id
2. Check authorization (confidence, permissions)
3. Create voice_command record (with correlation_id)
    ↓
Route to Policy Evaluator
    ├─ Explicit policy match → Execute directly
    └─ No match → voice_llm_fallback policy → LLM
                    ↓
                MCP Server (with tool permissions)
                    ↓
                Execute allowed tools
                    ↓
                Return response to Echonet (for TTS)
```

## Key Components

### 1. Database Schema (Migration 015)

**`voice_commands` table:**
- Tracks all voice interactions with full audit trail
- Links Echonet event_id to our internal correlation_id
- Stores voiceprint matching results and mapped person
- Records policy/LLM routing decisions and responses
- Captures processing time and actions taken

**`voiceprint_person_mapping` table:**
- Maps Echonet `voiceprint_user_id` (e.g., "alice") to `trusted_person_id`
- Allows multiple voiceprints per person
- Supports notes for mapping context

**`mcp_tool_permissions` table:**
- Controls which MCP tools can be called via voice
- Sets minimum voiceprint confidence requirements
- Supports 2FA requirements for sensitive tools
- Includes security levels (low, normal, high, critical)

### 2. Correlation ID System

**Middleware (`middleware.py`):**
- `CorrelationIDMiddleware`: Extracts or generates `X-Correlation-ID` header
- Stores in context variable for request lifecycle
- Adds to all log messages and response headers
- Format: `echo-{timestamp}-{random_id}`

**Usage:**
```python
# Auto-extracted from header or generated
correlation_id = get_correlation_id()

# Passed through all layers:
# API → Services → Database → MCP Tools → LLM
```

### 3. Voice Event Models (`voice_models.py`)

**`EchonetVoiceEvent`:**
- Matches Echonet upstream API payload spec
- Includes voiceprint identification fields
- Supports both `triggered` and `open_listen` modes

**`VoiceCommandResponse`:**
- Response format for Echonet
- Includes TTS text, actions taken, processing time
- Indicates whether LLM was used

### 4. Voice API Endpoints (`api_voice.py`)

**`POST /voice/listen`:**
- Main entry point for Echonet voice events
- Maps voiceprint → person
- Checks authorization
- Creates audit record
- Routes to policy/LLM
- Returns TTS response

**`POST /voice/mappings`:**
- Create voiceprint-to-person mappings
- `GET /voice/mappings` - List all mappings
- `GET /voice/mappings/{voiceprint_user_id}` - Get specific mapping

**`GET /voice/tools/permissions`:**
- List MCP tool voice permissions
- `GET /voice/tools/permissions/{tool_name}` - Get specific tool permissions

**`POST /voice/authorize`:**
- Check if command/tool is authorized
- Returns confidence requirements and 2FA needs

### 5. Service Layer (`services.py`)

**Voice Command Services:**
- `get_voiceprint_person_mapping()` - Lookup person by voiceprint ID
- `create_voice_command()` - Create audit record
- `update_voice_command_result()` - Update with processing results
- `get_voice_command_by_correlation()` - Retrieve by correlation ID

**Permission Services:**
- `get_mcp_tool_permission()` - Get tool permission settings
- `list_mcp_tool_permissions()` - List all tool permissions
- `check_voice_authorization()` - Authorize command/tool call

**Mapping Services:**
- `create_voiceprint_person_mapping()` - Create new mapping
- `list_voiceprint_mappings()` - List all mappings

### 6. MCP Tool Permissions

**Enhanced `call_tool()` in `mcp_server.py`:**
- Accepts `_context` in arguments with:
  - `correlation_id`: Track request origin
  - `source`: "voice_command" | "http" | etc.
  - `user_id`: Trusted person ID
  - `voiceprint_confidence`: Match confidence

**Permission Checks:**
1. Is tool `voice_enabled`?
2. Does confidence meet `requires_confidence`?
3. Does tool require 2FA?
4. Security level appropriate for action?

**Default Permissions (seeded in migration):**
```sql
-- Information/query tools: voice_enabled=1, confidence=0.75
list_policies, get_policy, query_scene, get_active_tracks,
get_visit_history, log_note

-- Management tools: voice_enabled=0, confidence=0.95 (disabled)
create_policy, update_policy, delete_policy
```

### 7. Default LLM Fallback Policy

Added to `004_add_policy_rules.sql`:

```sql
(
    'voice_llm_fallback',
    'Voice Command LLM Fallback',
    'Route voice commands to LLM when no explicit policy matches',
    1,  -- enabled
    1,  -- priority (lowest - evaluated last)
    '{"event_type": {"equals": "voice_command"}}',
    '[{"type": "route_to_llm", "allowed_tools": [...]}]',
    ...
)
```

This policy catches all voice commands that don't match specific policies and routes them to the LLM with a constrained set of allowed MCP tools.

## Authorization Flow

```python
def check_voice_authorization(text, voiceprint_confidence, tool_name):
    # 1. Check base confidence threshold
    if confidence < 0.75:
        return (False, "confidence_too_low", "request_telegram_confirmation")
    
    # 2. Check tool-specific permissions
    if tool_name:
        permission = get_mcp_tool_permission(tool_name)
        if not permission['voice_enabled']:
            return (False, "tool_not_voice_enabled", None)
        if confidence < permission['requires_confidence']:
            return (False, "below_threshold", "request_telegram_confirmation")
        if permission['requires_2fa']:
            return (False, "requires_2fa", "request_telegram_confirmation")
    
    # 3. Check security keywords
    if security_keywords in text and confidence < 0.95:
        return (False, "security_action_high_confidence", "request_telegram_confirmation")
    
    return (True, "authorized", None)
```

## Example Flow

### 1. Echonet sends voice event:
```json
POST /voice/listen
{
  "event_id": "echonet-1738449600-abc123",
  "ts": 1738449600,
  "source_id": "microphone",
  "room": "living-room",
  "text": "who is at the front door",
  "voiceprint_user_id": "alice",
  "voiceprint_confidence": 0.87,
  "mode": "triggered"
}
```

### 2. Policy server processes:
```python
# Generate correlation ID
correlation_id = "echo-1738449600-def456"

# Map voiceprint
trusted_person_id = 5  # alice → person #5

# Check authorization
allowed = True  # 0.87 > 0.75 threshold

# Create audit record
voice_cmd_id = 42

# Route to LLM (no explicit policy match)
llm_context = {
    "correlation_id": correlation_id,
    "user_id": "alice",
    "voiceprint_confidence": 0.87,
    "source": "voice_command"
}
```

### 3. LLM calls MCP tool:
```python
# LLM decides to call get_active_tracks
mcp_request = {
    "tool_name": "get_active_tracks",
    "arguments": {
        "camera_id": 1,  # front door
        "_context": llm_context
    }
}

# MCP server checks permissions
# - get_active_tracks: voice_enabled=True, requires_confidence=0.75
# - 0.87 >= 0.75 ✓
# - Executes tool
```

### 4. Response to Echonet:
```json
{
  "correlation_id": "echo-1738449600-def456",
  "handled": true,
  "response": "There's a delivery person at the front door with a package.",
  "user_acknowledged": "alice",
  "llm_used": true,
  "processing_time_ms": 342
}
```

### 5. Audit trail in database:
```sql
SELECT * FROM voice_commands WHERE correlation_id = 'echo-1738449600-def456';
-- Shows full journey: event → person → auth → LLM → response
```

## Security Features

1. **Voiceprint confidence gating:**
   - Low confidence (< 0.75): Require Telegram confirmation
   - Medium confidence (0.75-0.95): Allow info queries only
   - High confidence (> 0.95): Allow security actions

2. **Tool-level permissions:**
   - Each MCP tool has voice_enabled flag
   - Minimum confidence requirements per tool
   - 2FA requirements for critical tools

3. **Security keyword detection:**
   - "unlock", "disable", "delete" → require high confidence
   - Prevents accidental security breaches

4. **Full audit trail:**
   - Every voice command logged with correlation ID
   - Tracks original Echonet event, mapped person, actions taken
   - Enables forensic analysis

## Configuration

### Environment Variables
```bash
ECHOBELL_DB_PATH=/path/to/echoBell.db
```

### Echonet Target Registration
```json
POST http://echonet-server/register
{
  "name": "echobell",
  "base_url": "http://policy-server:8000",
  "phrases": ["hey echo", "echo"]
}
```

Echonet will POST to: `http://policy-server:8000/voice/listen`

## Testing

### 1. Create voiceprint mapping:
```bash
curl -X POST http://localhost:8000/voice/mappings \
  -H "Content-Type: application/json" \
  -d '{
    "voiceprint_user_id": "alice",
    "trusted_person_id": 1,
    "notes": "Alice - primary user"
  }'
```

### 2. Test voice command:
```bash
curl -X POST http://localhost:8000/voice/listen \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: test-123" \
  -d '{
    "event_id": "echonet-test-001",
    "ts": 1738449600,
    "source_id": "microphone",
    "room": "office",
    "text": "who is at the door",
    "voiceprint_user_id": "alice",
    "voiceprint_confidence": 0.92,
    "mode": "triggered"
  }'
```

### 3. Check authorization:
```bash
curl -X POST http://localhost:8000/voice/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "unlock the front door",
    "voiceprint_confidence": 0.85,
    "tool_name": "unlock_door"
  }'
```

### 4. List tool permissions:
```bash
curl http://localhost:8000/voice/tools/permissions?voice_enabled_only=true
```

## Future Enhancements

1. **LLM Integration:**
   - Connect to actual LLM service
   - Parse intent and extract tool names from commands
   - Multi-turn conversations with session tracking

2. **Telegram 2FA:**
   - Send confirmation requests to user's Telegram
   - Wait for approval before executing sensitive actions
   - Timeout and denial handling

3. **Policy Evaluation:**
   - Integrate with existing policy evaluator
   - Support voice-specific conditions (room, time, person)
   - Dynamic policy updates via voice

4. **Advanced Authorization:**
   - Role-based access control (admin, family, guest)
   - Temporary permissions (time-limited)
   - Geofencing (only allow commands from certain locations)

5. **Analytics:**
   - Voice command usage dashboard
   - Confidence score trends
   - Most common commands/tools

## Files Created/Modified

### New Files:
- `infra/db/migrations/015_add_voice_commands.sql` - Database schema
- `central/policy-server/middleware.py` - Correlation ID middleware
- `central/policy-server/voice_models.py` - Pydantic models
- `central/policy-server/api_voice.py` - Voice API endpoints

### Modified Files:
- `central/policy-server/server.py` - Add middleware and voice router
- `central/policy-server/services.py` - Add voice service functions
- `central/policy-server/mcp_server.py` - Add permission checking
- `infra/db/migrations/004_add_policy_rules.sql` - Add voice_llm_fallback policy

## Database Migrations

To apply the new schema:

```bash
# Run migration
sqlite3 echoBell.db < infra/db/migrations/015_add_voice_commands.sql

# Verify tables created
sqlite3 echoBell.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%voice%';"
```

Expected output:
- voice_commands
- voiceprint_person_mapping
- mcp_tool_permissions

## Logging

All voice commands are logged with correlation IDs:

```
[echo-1738449600-def456] Received voice event: who is at the door from alice
[echo-1738449600-def456] Mapped voiceprint 'alice' to person: Alice Smith
[echo-1738449600-def456] Routing to LLM: who is at the door
[echo-1738449600-def456] MCP tool call: get_active_tracks (source: voice_command, user: alice)
[echo-1738449600-def456] POST /voice/listen - 200 (342ms)
```

This enables easy tracking of entire request flow across system boundaries.
