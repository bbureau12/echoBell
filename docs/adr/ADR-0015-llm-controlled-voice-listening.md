# ADR-0015: LLM-Controlled Voice Listening Mode

**Status**: Accepted  
**Date**: 2026-02-02  
**Deciders**: System Architect  
**Related**: Voice Command Integration, Echonet Integration, MCP Server

---

## Context

EchoBell receives voice commands from Echonet edge devices via the `/voice/listen` endpoint. These commands are processed by the LLM through the MCP (Model Context Protocol) server. However, a critical limitation existed:

**Problem**: When a user provides an ambiguous or incomplete voice command (e.g., "unlock the door" when multiple doors exist), the LLM needs to ask for clarification. Previously, the user would need to say the wake word ("Hey Echobell") again to provide additional information, breaking the natural conversation flow.

**Example of the Problem**:
```
User: "Hey Echobell, unlock the door"
LLM: "Which door would you like to unlock?"
User: [Has to say "Hey Echobell" again]
User: "Hey Echobell, the front door"
```

This creates a poor user experience and makes multi-turn conversations impractical.

### Requirements

1. LLM must be able to request additional voice input from users
2. Users should not need to repeat the wake word for follow-up responses
3. Microphone should not stay open indefinitely (security/privacy risk)
4. Solution must work with existing Echonet infrastructure
5. Must maintain security/authorization model (voiceprint confidence)
6. All interactions must be auditable (correlation IDs, logging)

### Constraints

- Echonet edge devices already have a `/state` endpoint for controlling listen modes
- Echonet supports three modes: `trigger` (wake word required), `open_listen` (continuous), `inactive` (off)
- Echonet automatically times out from `open_listen` to `trigger` after configurable duration (default 30s)
- MCP protocol must be used for LLM interaction (no direct API calls from LLM)
- Cannot modify Echonet firmware (must use existing API)

---

## Decision

We will implement **LLM-controlled Echonet listening mode** through the MCP server, allowing the LLM to:

1. **Activate open listening mode** when it needs more information from the user
2. **Deactivate listening mode** when the conversation is complete
3. **Query Echonet status** to see which instances are available and their current modes

### Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────┐
│   Echonet   │────────▶│ Policy Server│────────▶│   LLM   │
│  (Edge Dev) │  Voice  │  (FastAPI)   │   MCP   │  (MCP)  │
└─────────────┘  Events └──────────────┘  Tools  └─────────┘
       ▲                        │                       │
       │      PUT /state        │   activate_echonet_   │
       │   mode=open_listen     │      listening()      │
       └────────────────────────┴───────────────────────┘
              State Control Flow
```

### Components

1. **EchonetModeService** (`echonet_mode_service.py`)
   - Low-level HTTP client for Echonet `/state` endpoint
   - `activate_listening()` - PUT with mode="open_listen"
   - `deactivate_listening()` - PUT with mode="trigger"
   - `get_echonet_state()` - GET current state
   - Uses httpx with API key authentication

2. **Service Layer Integration** (`services.py`)
   - `activate_echonet_listening()` - Wrapper with defaults
   - `deactivate_echonet_listening()` - Wrapper with defaults
   - `get_echonet_instances_status()` - Query all instances
   - Lazy-loaded to avoid circular dependencies

3. **MCP Tools** (`mcp_server.py`)
   - `activate_echonet_listening` - Exposed to LLM
   - `deactivate_echonet_listening` - Exposed to LLM
   - `get_echonet_status` - Query instances
   - Auto-selects first Echonet if URL not provided

4. **Tool Permissions** (`mcp_tool_permissions` table)
   - All three tools: `voice_enabled=1`, `requires_confidence=0.75`
   - Security level: `normal` (activate/deactivate), `low` (status)

### Conversation Flow

**Before (broken)**:
```
User: "Hey Echobell, unlock the door"
LLM: "Which door?" (user can't hear this if not sent via TTS)
[User must say wake word again]
User: "Hey Echobell, the front door"
```

**After (natural)**:
```
User: "Hey Echobell, unlock the door"
LLM: [Calls activate_echonet_listening]
LLM: "Which door would you like to unlock?"
User: "The front door" (no wake word needed!)
LLM: [Processes unlock]
LLM: [Calls deactivate_echonet_listening]
```

---

## Consequences

### Positive

1. **Natural Conversations**: Users can have multi-turn dialogs without repeating wake word
2. **Better UX**: LLM can ask clarifying questions and gather complete information
3. **Security Maintained**: Still requires initial voiceprint authentication and confidence thresholds
4. **Auditable**: All activations logged in `voice_commands` table with correlation IDs
5. **Safe Defaults**: Automatic timeout prevents stuck-open microphones
6. **Flexible**: Works with multiple Echonet instances via mDNS discovery
7. **MCP Native**: Uses standard MCP tool protocol, works with any MCP client

### Negative

1. **Timeout Management**: LLM must be aware of 30s timeout and manage expectations
2. **Network Dependency**: Requires reliable connectivity between Policy Server and Echonet
3. **API Key Management**: Another credential to secure (`ECHONET_API_KEY`)
4. **Testing Complexity**: End-to-end testing requires live Echonet instance
5. **No Session Tracking**: Currently no link between activate/deactivate pairs (future enhancement)

### Risks

| Risk | Mitigation |
|------|------------|
| Microphone stuck open | Echonet enforces automatic timeout (30s default) |
| Unauthorized activation | Requires voiceprint confidence >= 0.75, logged in database |
| Network failure during conversation | Timeout will still trigger, user can say wake word again |
| LLM forgets to deactivate | Automatic timeout prevents indefinite listening |
| Multiple concurrent conversations | Future: Add session tracking and zone awareness |

---

## Implementation Details

### Database Schema

**mcp_tool_permissions** entries:
```sql
INSERT INTO mcp_tool_permissions (tool_name, voice_enabled, requires_confidence, security_level)
VALUES 
  ('activate_echonet_listening', 1, 0.75, 'normal'),
  ('deactivate_echonet_listening', 1, 0.75, 'normal'),
  ('get_echonet_status', 1, 0.75, 'low');
```

### API Contract

**Echonet PUT /state**:
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

### MCP Tool Schema

```json
{
  "name": "activate_echonet_listening",
  "description": "Activate open listening mode for multi-turn conversation",
  "inputSchema": {
    "type": "object",
    "properties": {
      "echonet_url": {"type": "string", "description": "Optional, auto-detected"},
      "target_name": {"type": "string", "default": "echobell"},
      "reason": {"type": "string", "description": "Why activating"}
    }
  }
}
```

### Authorization Flow

1. Voice command arrives with voiceprint confidence
2. Middleware extracts/generates correlation ID
3. Service layer processes command
4. LLM receives command via MCP context
5. If ambiguous, LLM calls `activate_echonet_listening`
6. MCP server checks tool permissions (confidence >= 0.75)
7. Service layer calls EchonetModeService
8. HTTP PUT to Echonet `/state` endpoint
9. Echonet enters `open_listen` mode
10. User speaks follow-up (no wake word)
11. Echonet sends to Policy Server with same session context
12. LLM processes, then calls `deactivate_echonet_listening`
13. Or timeout triggers automatic return to `trigger` mode

---

## Alternatives Considered

### 1. Client-Side Wake Word Bypass

**Approach**: Echonet detects follow-up questions in LLM response and auto-activates listening

**Rejected because**:
- Couples Echonet to LLM response format
- No LLM control over when to listen
- Can't handle complex multi-step flows
- Harder to audit (decision made on edge)

### 2. Always-On Listening After Wake Word

**Approach**: Echonet stays in `open_listen` for fixed duration after any wake word

**Rejected because**:
- Security/privacy risk (microphone open when not needed)
- No semantic understanding of when conversation ends
- Wastes resources listening when command complete
- User has no control over when mic is active

### 3. Telegram-Based Follow-Up

**Approach**: LLM sends clarifying questions via Telegram, user types response

**Rejected because**:
- Breaks voice conversation flow
- Forces mode switch (voice → text → voice)
- Poor UX for simple clarifications
- Telegram might not be available/configured

### 4. Voice Session Tokens

**Approach**: Issue temporary session tokens that allow multi-turn without wake word

**Rejected because**:
- Complex token management on edge devices
- Still need way to signal "ready for follow-up"
- Doesn't solve core problem of LLM control
- Over-engineered for the use case

---

## Future Enhancements

### Planned (Q1 2026)

1. **Session Tracking**: Link activate/deactivate pairs via `session_id` in `voice_commands`
2. **Adaptive Timeout**: Extend timeout if user still speaking (VAD-based)
3. **Zone-Aware Activation**: Only activate Echonet in user's current zone
4. **Confidence Decay**: Require higher confidence for extended conversations

### Roadmap (Q2 2026)

1. **Interrupt Handling**: Support "wait", "stop", "cancel" during LLM questions
2. **Multi-Echonet Coordination**: Follow user room-to-room during conversation
3. **Emotion Detection**: Adjust conversation based on user emotion/frustration
4. **Speaker Diarization**: Handle multi-person conversations

---

## Related Decisions

- **Voice Command Integration**: Foundation for receiving commands from Echonet
- **Correlation ID Tracking**: Enables linking multi-turn conversations
- **Echonet Discovery**: Auto-discovery of Echonet instances via mDNS
- **MCP Tool Permissions**: Security model for voice-triggered tools

---

## References

- Implementation: `central/policy-server/echonet_mode_service.py`
- Service Layer: `central/policy-server/services.py`
- MCP Tools: `central/policy-server/mcp_server.py`
- Migration: `infra/db/migrations/015_add_voice_commands.sql`
- Documentation: `docs/ECHONET_LISTENING_MODE.md`
- Test: `tests/test_echonet_listening.py`

---

## Approval

**Accepted**: 2026-02-02  
**Implementation Status**: Complete  
**Production Ready**: Yes (pending integration testing)

---

## Lessons Learned

1. **Leverage Existing APIs**: Echonet already had `/state` endpoint - no firmware changes needed
2. **Automatic Safety**: Timeout on edge device prevents policy server bugs from leaving mic open
3. **MCP Simplicity**: Adding new tools to MCP server is straightforward and well-tested
4. **Service Layer Pattern**: Shared service layer between FastAPI and MCP avoided duplication
5. **Documentation First**: Writing docs clarified edge cases before implementation
