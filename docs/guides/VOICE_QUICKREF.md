# Voice Command Integration - Quick Reference

## Quick Start

### 1. Apply Database Migration
```bash
sqlite3 echoBell.db < infra/db/migrations/015_add_voice_commands.sql
```

### 2. Start Policy Server
```bash
cd central/policy-server
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 3. Create Voiceprint Mapping
```bash
# Using CLI
python central/policy-server/voice_cli.py mappings create alice 1 "Primary user"

# Using API
curl -X POST http://localhost:8000/voice/mappings \
  -H "Content-Type: application/json" \
  -d '{"voiceprint_user_id": "alice", "trusted_person_id": 1}'
```

### 4. Test Voice Command
```bash
curl -X POST http://localhost:8000/voice/listen \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "test-001",
    "ts": 1738449600,
    "source_id": "microphone",
    "text": "who is at the door",
    "voiceprint_user_id": "alice",
    "voiceprint_confidence": 0.92,
    "mode": "triggered"
  }'
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/voice/listen` | POST | Receive voice events from Echonet |
| `/voice/mappings` | GET | List voiceprint mappings |
| `/voice/mappings` | POST | Create voiceprint mapping |
| `/voice/mappings/{id}` | GET | Get specific mapping |
| `/voice/tools/permissions` | GET | List tool permissions |
| `/voice/tools/permissions/{tool}` | GET | Get tool permission |
| `/voice/authorize` | POST | Check command authorization |

## CLI Commands

```bash
# Mappings
python voice_cli.py mappings list
python voice_cli.py mappings create <voiceprint_id> <person_id> [notes]

# Commands
python voice_cli.py commands list [--limit 20]
python voice_cli.py commands show <correlation_id>

# Tools
python voice_cli.py tools list [--voice-only]
```

## Confidence Thresholds

| Confidence | Allowed Actions |
|------------|----------------|
| < 0.75 | ❌ Deny all, request 2FA |
| 0.75 - 0.80 | ✅ Info queries (list_policies, query_scene) |
| 0.80 - 0.95 | ✅ Scene tracking (get_active_tracks, get_visit_history) |
| > 0.95 | ✅ Most actions (except critical tools) |

## Tool Permissions (Default)

| Tool | Voice Enabled | Min Confidence | Security Level |
|------|--------------|----------------|---------------|
| `list_policies` | ✅ | 0.75 | low |
| `get_policy` | ✅ | 0.75 | low |
| `query_scene` | ✅ | 0.75 | normal |
| `get_active_tracks` | ✅ | 0.75 | normal |
| `get_visit_history` | ✅ | 0.80 | normal |
| `log_note` | ✅ | 0.75 | low |
| `create_policy` | ❌ | 0.95 | critical |
| `update_policy` | ❌ | 0.95 | critical |
| `delete_policy` | ❌ | 0.95 | critical |

## Database Tables

### `voice_commands`
```sql
-- Full audit trail of voice interactions
correlation_id TEXT UNIQUE    -- Our tracking ID
echonet_event_id TEXT         -- Upstream event ID
voiceprint_user_id TEXT       -- Speaker ID from Echonet
trusted_person_id INTEGER     -- Mapped person
text TEXT                     -- Command text
auth_result TEXT              -- allowed/denied/2fa_required
llm_used INTEGER              -- Was LLM involved?
response_text TEXT            -- What we told the user
processing_time_ms INTEGER    -- Performance metric
```

### `voiceprint_person_mapping`
```sql
-- Links Echonet voiceprint IDs to trusted persons
voiceprint_user_id TEXT UNIQUE
trusted_person_id INTEGER
```

### `mcp_tool_permissions`
```sql
-- Controls voice access to MCP tools
tool_name TEXT PRIMARY KEY
voice_enabled INTEGER         -- 1 = can call via voice
requires_confidence REAL      -- Min voiceprint confidence
requires_2fa INTEGER          -- Always need 2FA
security_level TEXT           -- low/normal/high/critical
```

## Correlation ID Format

```
echo-{timestamp}-{random_id}

Example: echo-1738449600-abc123def456
         └─── Unix timestamp
                        └─── 12-char random hex
```

## MCP Tool Context

When LLM calls MCP tool via voice command:

```json
{
  "tool_name": "query_scene",
  "arguments": {
    "camera_id": 1,
    "_context": {
      "correlation_id": "echo-1738449600-abc123",
      "source": "voice_command",
      "user_id": "alice",
      "voiceprint_confidence": 0.92
    }
  }
}
```

## Common Issues

### Voiceprint Not Mapped
**Symptom**: "No mapping found for voiceprint: alice"
**Solution**: Create mapping with `voice_cli.py mappings create alice <person_id>`

### Confidence Too Low
**Symptom**: "voiceprint_confidence_too_low"
**Solution**: 
1. Check Echonet voiceprint quality
2. Enroll more voice samples
3. Or request Telegram 2FA

### Tool Not Voice Enabled
**Symptom**: "Tool 'xxx' is not enabled for voice commands"
**Solution**: 
```sql
UPDATE mcp_tool_permissions 
SET voice_enabled = 1 
WHERE tool_name = 'xxx';
```

### Missing Correlation ID in Logs
**Symptom**: Logs don't show `[echo-...]` prefix
**Solution**: 
1. Check middleware is loaded: Look for "Correlation ID middleware enabled" on startup
2. Pass `X-Correlation-ID` header in requests
3. Middleware will generate if missing

## Testing Checklist

- [ ] Migration applied (`015_add_voice_commands.sql`)
- [ ] Policy server starts without errors
- [ ] Middleware loaded (check startup logs)
- [ ] Voice router available (check startup logs)
- [ ] At least one voiceprint mapping created
- [ ] Test voice command succeeds
- [ ] Correlation ID appears in logs
- [ ] Voice command stored in database
- [ ] Authorization check works

## Monitoring

### Check Recent Voice Commands
```sql
SELECT 
  correlation_id,
  voiceprint_user_id,
  text,
  auth_result,
  llm_used,
  datetime(timestamp, 'unixepoch')
FROM voice_commands 
ORDER BY timestamp DESC 
LIMIT 10;
```

### Check Authorization Denials
```sql
SELECT 
  correlation_id,
  text,
  auth_result,
  auth_reason,
  voiceprint_confidence
FROM voice_commands 
WHERE auth_result != 'allowed'
ORDER BY timestamp DESC;
```

### Check LLM Usage
```sql
SELECT 
  COUNT(*) as total,
  SUM(llm_used) as llm_count,
  AVG(processing_time_ms) as avg_ms
FROM voice_commands;
```

## Echonet Integration

Register EchoBell as target:
```bash
POST http://echonet-server/register
{
  "name": "echobell",
  "base_url": "http://policy-server:8000",
  "phrases": ["hey echo", "echo bell"]
}
```

Echonet environment variables:
```bash
ECHONET_VOICEPRINT_ENABLED=true
ECHONET_VOICEPRINT_API_URL=http://edge-server:8080
ECHONET_VOICEPRINT_SIMILARITY_THRESHOLD=0.75
```

## Support

- **Documentation**: `docs/VOICE_COMMAND_INTEGRATION.md`
- **Summary**: `docs/VOICE_COMMAND_SUMMARY.md`
- **Tests**: `tests/test_voice_integration.py`
- **CLI**: `central/policy-server/voice_cli.py`
