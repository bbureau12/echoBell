# LLM Integration Package

Multi-turn conversational AI for echoBell doorbell system.

## Features

- ✅ **Distributed architecture** - LLM runs on separate server (local or cloud)
- ✅ **Multiple backends** - Local (Vicuna, Llama), Cloud (Claude, OpenAI, Azure)
- ✅ **HTTP/API communication** - Flexible network topology
- ✅ **Async/await** - Clean conversation flow without queues
- ✅ **ASR integration** - Waits for user responses
- ✅ **Tool calling** - LLM can unlock doors, send alerts, query context

## Quick Start

### 1. Choose Your LLM Backend

**Option A: Local LLM (Vicuna, Llama, etc.)**
```bash
# See docs/VICUNA_SETUP.md for full installation guide
pip install "fschat[model_worker,webui]"
python -m fastchat.serve.openai_api_server --host 0.0.0.0 --port 8000
```

**Option B: Cloud API (Claude)**
```bash
# Just need API key - no server setup
export ANTHROPIC_API_KEY=sk-ant-...
```

**Option C: Cloud API (OpenAI)**
```bash
export OPENAI_API_KEY=sk-...
```

### 2. Configure echoBell Device

Edit `config/llm_config.toml`:

```toml
[llm]
provider = "vicuna"  # or "claude", "openai"

# For local LLM
[llm.vicuna]
base_url = "http://192.168.1.100:8000"
model = "vicuna-13b-v1.5"

# For Claude
[llm.claude]
api_key = "${ANTHROPIC_API_KEY}"
model = "claude-3-5-sonnet-20241022"

# For OpenAI
[llm.openai]
api_key = "${OPENAI_API_KEY}"
model = "gpt-4"
```

Or use environment variables (overrides config file):
```bash
# For local LLM
export LLM_PROVIDER=vicuna
export VICUNA_BASE_URL=http://192.168.1.100:8000

# For Claude
export LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...

# For OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
```

### 3. Use in Code

```python
from packages.llm import create_handler_from_config

# Create handler from config file
# Automatically uses configured provider (vicuna/claude/openai)
handler = create_handler_from_config(
    conn=db_conn,
    asr_service=asr,
    tts_service=tts
)

# Handle doorbell interaction
result = await handler.handle_doorbell_audio(
    audio_path="/path/to/doorbell.wav",
    context={
        "camera_id": 1,
        "visitor_info": {"face_detected": True}
    }
)

print(f"Action: {result['action']}")
# Result: {"status": "complete", "action": "unlock_door", "summary": "..."}
```

## Architecture

**Distributed Setup (Local LLM):**
```
┌─────────────────────┐
│  echoBell Device    │  ← Raspberry Pi, NUC, etc.
│  (192.168.1.50)     │
│                     │
│  ConversationHandler│  ← Your code
│         ↓           │
│  LLMClient          │  ← HTTP/API client
└──────────┬──────────┘
           │
           │ HTTP/HTTPS
           │
┌──────────▼──────────┐
│  LLM Backend        │  ← Local server OR cloud API
│                     │
│  Local:             │
│  - FastChat/vLLM    │
│  - Vicuna/Llama     │
│  - GPU server       │
│                     │
│  Cloud:             │
│  - Claude API       │
│  - OpenAI API       │
│  - Azure OpenAI     │
└─────────────────────┘
```

## API Reference

### ConversationHandler

Main class for handling multi-turn conversations.

```python
from packages.llm import ConversationHandler

handler = ConversationHandler(
    conn=db_connection,
    asr_service=asr_service,      # For listening to user
    tts_service=tts_service,      # For speaking to user
    llm_provider="vicuna",        # "vicuna", "claude", "openai"
    llm_config={
        # Config depends on provider:
        # Vicuna: {"base_url": "http://...", "model": "..."}
        # Claude: {"api_key": "sk-ant-..."}
        # OpenAI: {"api_key": "sk-...", "model": "gpt-4"}
    }
)
```

**Methods:**

- `await handle_doorbell_audio(audio_path, context)` - Handle conversation
- Returns: `{"status": "complete", "action": "unlock_door", "summary": "..."}`

### Config Loader

Load configuration from TOML file or environment.

```python
from packages.llm import load_llm_config, create_handler_from_config

# Load config (respects LLM_PROVIDER environment variable)
config = load_llm_config()
# Returns: {"provider": "vicuna", "vicuna": {"base_url": "...", ...}}
#       or {"provider": "claude", "claude": {"api_key": "...", ...}}

# Create handler from config (automatically selects provider)
handler = create_handler_from_config(conn, asr, tts)
```

### LLM Clients

Low-level clients for different backends.

```python
from packages.llm import create_llm_client

# Local LLM (Vicuna, Llama, etc.)
client = create_llm_client(
    "vicuna",
    base_url="http://192.168.1.100:8000",
    model="vicuna-13b-v1.5",
    temperature=0.7
)

# Claude API
client = create_llm_client(
    "claude",
    api_key="sk-ant-...",
    model="claude-3-5-sonnet-20241022"
)

# OpenAI API
client = create_llm_client(
    "openai",
    api_key="sk-...",
    model="gpt-4",
    temperature=0.7
)

# Use client
response = await client.create_message(
    messages=[{"role": "user", "content": "Hello"}],
    tools=[...],
    system="You are a doorbell assistant"
)
```

## Conversation Flow

1. **Doorbell rings** → Audio captured
2. **Transcribe** → Convert audio to text
3. **Send to LLM** → Initial prompt with context
4. **LLM responds** → May ask question via tool call
5. **If tool = activate_asr:**
   - Speak question via TTS
   - Activate ASR (await user response)
   - Send response back to LLM
   - Repeat from step 4
6. **If tool = execute_action:**
   - Execute (unlock, alert, etc.)
   - Return result to policy layer

## Tool Calling

LLM has access to these tools:

### activate_asr
Ask the visitor a question and wait for response.

```json
{
  "tool": "activate_asr",
  "parameters": {
    "question": "Who are you here to see?",
    "timeout_seconds": 30
  }
}
```

### speak_to_visitor
Speak to visitor without waiting for response.

```json
{
  "tool": "speak_to_visitor",
  "parameters": {
    "message": "Please wait, I'll notify the homeowner."
  }
}
```

### execute_action
Take final action and end conversation.

```json
{
  "tool": "execute_action",
  "parameters": {
    "action": "unlock_door",  // or "send_alert", "deny_access", "no_action"
    "parameters": {}
  }
}
```

### query_policy_context
Get additional context from policy system.

```json
{
  "tool": "query_policy_context",
  "parameters": {
    "query_type": "trusted_faces"  // or "quiet_hours", "recent_visits", "active_events"
  }
}
```

## Configuration

### Environment Variables

```bash
# LLM Provider
export LLM_PROVIDER=vicuna  # or "claude", "openai"

# Vicuna Settings
export VICUNA_BASE_URL=http://192.168.1.100:8000
export VICUNA_MODEL=vicuna-13b-v1.5
export VICUNA_TEMPERATURE=0.7
export VICUNA_MAX_TOKENS=2048

# Conversation Settings
export CONVERSATION_MAX_TURNS=10
export ASR_TIMEOUT=30
export ENABLE_TOOL_CALLING=true

# Network Settings
export LLM_TIMEOUT=60
export LLM_RETRY_ATTEMPTS=3
```

### Config File

Edit `config/llm_config.toml`:

```toml
[llm]
provider = vicuna

[llm.vicuna]
base_url = http://192.168.1.100:8000
model = vicuna-13b-v1.5
temperature = 0.7
max_tokens = 2048

[conversation]
max_turns = 10
asr_timeout = 30
enable_tool_calling = true

[network]
timeout = 60
retry_attempts = 3
retry_delay = 2
```

## Testing

### Test Connection

```python
import asyncio
import aiohttp

async def test():
    async with aiohttp.ClientSession() as session:
        async with session.get("http://192.168.1.100:8000/v1/models") as resp:
            print(await resp.json())

asyncio.run(test())
```

### Run Example

```bash
python examples/llm_conversation_example.py
```

## Documentation

- **Setup:** `docs/VICUNA_SETUP.md` - Install Vicuna server
- **Networking:** `docs/DISTRIBUTED_LLM_SETUP.md` - Configure distributed architecture
- **MCP:** `central/policy-server/MCP_SETUP_GUIDE.md` - Claude Desktop integration

## Database Schema

Conversations tracked in `llm_conversations` table:

```sql
CREATE TABLE llm_conversations (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE,
    camera_id INTEGER,
    started_ts INTEGER,
    completed_ts INTEGER,
    state TEXT,
    context_json TEXT,
    messages_json TEXT,
    result_action TEXT
);
```

Query recent conversations:
```sql
SELECT 
    session_id,
    camera_id,
    datetime(started_ts, 'unixepoch') as started,
    state,
    result_action
FROM llm_conversations
ORDER BY started_ts DESC
LIMIT 20;
```

## Performance

### Network Latency
- Same subnet: ~1-5ms (negligible)
- WiFi: ~10-50ms (acceptable)
- Total overhead: <50ms

### Bandwidth
- Request: ~1-5 KB
- Response: ~5-20 KB
- Per conversation: ~50-200 KB

### Response Time
- Transcription: 500ms
- Network: 10ms
- LLM generation: 1-3s
- TTS: 800ms
- **Total: ~2-5 seconds**

## Troubleshooting

### Connection refused
```bash
# Check if LLM server is accessible
curl http://192.168.1.100:8000/v1/models

# Check firewall
sudo ufw allow 8000/tcp

# Ensure FastChat bound to 0.0.0.0
python -m fastchat.serve.openai_api_server --host 0.0.0.0 --port 8000
```

### Slow responses
- Use gigabit Ethernet (not WiFi)
- Upgrade to vLLM (3-5x faster)
- Reduce max_tokens
- Use smaller model (vicuna-7b)

### LLM not using tools correctly
- Add few-shot examples to system prompt
- Check tool definitions in `_get_tools()`
- Enable verbose logging

## Examples

See `examples/llm_conversation_example.py` for:
- Basic conversation flow
- Multi-turn example
- Policy integration
- Mock ASR/TTS services

## License

Part of echoBell project.
