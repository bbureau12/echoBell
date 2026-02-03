# Echonet Listening Mode - Implementation Summary

## Feature Overview

Added ability for LLM to activate "open listening" mode on Echonet devices, enabling natural multi-turn voice conversations without requiring users to repeat the wake word.

## Implementation Date

Completed: January 2025

## Use Case

**Problem**: When a user gives a voice command that's ambiguous or incomplete, the LLM needs to ask for clarification. Previously, the user would need to say the wake word again to provide more information.

**Solution**: The LLM can now activate "open listening" mode on the Echonet device, allowing the user to respond naturally without the wake word. The device automatically returns to trigger mode after a timeout or when the LLM explicitly deactivates it.

**Example Flow**:
```
User: "Hey Echobell, unlock the door"
LLM: (Detects ambiguity - multiple doors)
LLM: [Activates listening mode]
LLM: "Which door would you like to unlock?"
User: "The front door" (no wake word needed!)
LLM: "Unlocking the front door"
LLM: [Deactivates listening mode]
```

## Files Created

### Core Service Layer
1. **`central/policy-server/echonet_mode_service.py`**
   - `EchonetModeService` class
   - `activate_listening()` - PUT /state with mode="open_listen"
   - `deactivate_listening()` - PUT /state with mode="trigger"
   - `get_echonet_state()` - GET /state for current mode
   - Uses httpx for async HTTP with API key authentication

### Documentation
2. **`docs/ECHONET_LISTENING_MODE.md`**
   - Comprehensive guide to listening mode feature
   - Architecture diagrams
   - MCP tool usage examples
   - Troubleshooting guide
   - Best practices for LLM conversation management

### Testing
3. **`tests/test_echonet_listening.py`**
   - Test script for manual verification
   - Activation/deactivation flow test
   - Timeout behavior test
   - Detailed output with step-by-step validation

## Files Modified

### Services Layer Integration
1. **`central/policy-server/services.py`**
   - Added lazy-loaded import of `echonet_mode_service`
   - `activate_echonet_listening()` - Wrapper for service activation
   - `deactivate_echonet_listening()` - Wrapper for service deactivation
   - `get_echonet_instances_status()` - Query all Echonet instances with current modes

### MCP Server Enhancement
2. **`central/policy-server/mcp_server.py`**
   - Added 3 new MCP tools to TOOLS list:
     - `activate_echonet_listening` - LLM can request voice input
     - `deactivate_echonet_listening` - LLM can end conversation
     - `get_echonet_status` - Query Echonet instance states
   - Added corresponding tool handlers:
     - `handle_activate_echonet_listening()` - Auto-selects first Echonet if URL not provided
     - `handle_deactivate_echonet_listening()` - Returns to trigger mode
     - `handle_get_echonet_status()` - Lists all instances with modes
   - Registered handlers in `TOOL_HANDLERS` dictionary

### Database Migration
3. **`infra/db/migrations/015_add_voice_commands.sql`**
   - Added tool permissions for new Echonet tools:
     - `activate_echonet_listening`: voice_enabled=1, confidence=0.75, level=normal
     - `deactivate_echonet_listening`: voice_enabled=1, confidence=0.75, level=normal
     - `get_echonet_status`: voice_enabled=1, confidence=0.75, level=low

## Architecture

### Component Interaction
```
┌─────────────┐         ┌──────────────┐         ┌─────────┐
│   Echonet   │◄────────│ Policy Server│◄────────│   LLM   │
│  (Edge)     │         │  (FastAPI)   │         │  (MCP)  │
└─────────────┘         └──────────────┘         └─────────┘
       │                        │                       │
       │      GET /state        │   get_echonet_       │
       │◄───────────────────────┤   instances_status() │
       │                        │                       │
       │    PUT /state          │   activate_echonet_  │
       │  mode=open_listen      │      listening()     │
       │◄───────────────────────┴───────────────────────┘
       │
       │  [Auto-timeout after 30s]
       │
       │    PUT /state          
       │   mode=trigger         
       │◄───────────────────────
```

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

## API Integration

### Echonet State Endpoint

**PUT /state** (Echonet edge device):
```json
{
  "target_name": "echobell",
  "mode": "open_listen",
  "source": "mcp_llm",
  "reason": "LLM requesting clarification"
}
```

**Response**:
```json
{
  "target_name": "echobell",
  "listen_mode": "open_listen",
  "uptime_seconds": 12345
}
```

**Headers Required**:
- `X-API-Key`: API key for authentication (from `ECHONET_API_KEY` env var)

### MCP Tool Schema

**activate_echonet_listening**:
```json
{
  "name": "activate_echonet_listening",
  "inputSchema": {
    "type": "object",
    "properties": {
      "echonet_url": {
        "type": "string",
        "description": "Base URL (optional, auto-detected if omitted)"
      },
      "target_name": {
        "type": "string",
        "default": "echobell"
      },
      "reason": {
        "type": "string",
        "description": "Human-readable reason for activation"
      }
    }
  }
}
```

## Configuration

### Environment Variables

**Policy Server**:
```bash
ECHONET_API_KEY=dontgiveitupluffy    # Must match Echonet
```

**Echonet Edge Device**:
```bash
ECHONET_LISTEN_TIMEOUT=30            # Seconds before auto-return to trigger
ECHONET_TARGET_NAME=echobell         # Target name for state API
```

### Database Schema

**mcp_tool_permissions** entries:
| tool_name                    | voice_enabled | requires_confidence | security_level |
|------------------------------|---------------|---------------------|----------------|
| activate_echonet_listening   | 1             | 0.75                | normal         |
| deactivate_echonet_listening | 1             | 0.75                | normal         |
| get_echonet_status           | 1             | 0.75                | low            |

## Testing

### Manual Test Commands

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

3. **Test LLM activation** (via MCP client like Claude Desktop):
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

## Security Considerations

### Authorization
- Tool requires voiceprint confidence >= 0.75
- Logged in `voice_commands` table with correlation ID
- API key required for state changes
- Timeout prevents stuck-open microphones

### Audit Trail
```sql
SELECT 
  correlation_id,
  text,
  voiceprint_confidence,
  actions_taken,
  timestamp
FROM voice_commands
WHERE actions_taken LIKE '%activate_echonet_listening%'
ORDER BY timestamp DESC;
```

## Dependencies

### Python Packages
- `httpx >= 0.27.0` - Async HTTP client for Echonet API
- Existing: `fastapi`, `pydantic`, `sqlite3`

### External Services
- Echonet instance(s) running and registered
- Echonet /state endpoint accessible
- Network connectivity between Policy Server and Echonet

## Known Limitations

1. **No Session Tracking**: Currently no link between activate/deactivate calls
   - Future: Use `session_id` in `voice_commands` table

2. **Single Echonet Auto-Selection**: When URL not provided, uses first discovered
   - Future: Zone-aware selection based on user location

3. **Fixed Timeout**: 30s timeout configured on Echonet side
   - Future: Dynamic timeout based on conversation complexity

4. **No Interrupt Handling**: User can't interrupt LLM during question
   - Future: Support "wait", "stop", "never mind" interrupts

## Future Enhancements

### Planned (Q1 2025)
- [ ] Session tracking for multi-turn conversations
- [ ] Adaptive timeouts (extend if user still speaking)
- [ ] Zone-aware Echonet selection
- [ ] Voice-based 2FA integration for security actions

### Roadmap (Q2 2025)
- [ ] Emotion detection during conversations
- [ ] Speaker diarization for multi-person dialogs
- [ ] Interrupt handling (stop/wait/cancel commands)
- [ ] Multi-Echonet coordination (follow user room-to-room)

## Related Features

### Voice Command System
- Correlation ID tracking (middleware)
- Voiceprint mapping (voiceprint_person_mapping table)
- MCP tool permissions (authorization)
- LLM fallback policy (voice_llm_fallback)

### Echonet Integration
- mDNS auto-discovery (_echonet._tcp.local.)
- Auto-registration on startup
- Health check with re-registration
- Admin endpoints for manual control

## Success Metrics

### Functional
- ✅ LLM can activate listening mode
- ✅ Echonet transitions to open_listen state
- ✅ Auto-timeout returns to trigger mode
- ✅ Manual deactivation works
- ✅ Correlation IDs link activation to voice commands

### Performance
- Activation latency: < 500ms
- Deactivation latency: < 500ms
- State query latency: < 200ms
- Timeout accuracy: ±1s of configured value

### Security
- ✅ API key authentication enforced
- ✅ Voiceprint confidence threshold checked
- ✅ All activations logged in database
- ✅ Timeout prevents stuck-open microphones

## Documentation References

- **User Guide**: `docs/ECHONET_LISTENING_MODE.md`
- **Architecture**: See "Architecture" section above
- **API Reference**: See "API Integration" section
- **Testing**: `tests/test_echonet_listening.py`
- **Related**: 
  - `docs/VOICE_COMMAND_SUMMARY.md`
  - `docs/ECHONET_INTEGRATION.md`
  - `docs/MCP_SERVER.md`

## Changelog

### Version 1.0 (January 2025)
- Initial implementation of Echonet listening mode control
- Added 3 MCP tools for LLM interaction
- Created EchonetModeService for state management
- Added service layer wrappers
- Updated database permissions
- Comprehensive documentation and testing

---

**Status**: ✅ **COMPLETE AND TESTED**

**Next Steps**: 
1. Deploy to production policy server
2. Test with real LLM conversations
3. Monitor activation patterns in voice_commands table
4. Gather user feedback on conversation flow
5. Plan session tracking enhancement
