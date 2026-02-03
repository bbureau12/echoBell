# Distributed LLM Setup Guide

## Architecture Overview

echoBell uses a **distributed architecture** where the LLM server can run on a separate machine with powerful GPU(s):

```
┌─────────────────────────────────┐
│  echoBell "Brains" Device       │  ← Raspberry Pi, NUC, or low-power PC
│  (192.168.1.50)                 │
│                                 │
│  - Policy layer                 │
│  - ASR/TTS services             │
│  - ConversationHandler          │
│  - VicunaClient (HTTP)          │  ← Makes HTTP requests
└──────────────┬──────────────────┘
               │
               │ HTTP API
               │ Port 8000
               │
┌──────────────▼──────────────────┐
│  LLM Server                     │  ← GPU workstation/server
│  (192.168.1.100)                │
│                                 │
│  - NVIDIA GPU (RTX 4090, etc.)  │
│  - Vicuna model                 │
│  - FastChat/vLLM server         │
└─────────────────────────────────┘
```

## Benefits of Distributed Setup

- ✅ **Separate concerns** - Doorbell logic on one device, AI on another
- ✅ **GPU flexibility** - Use powerful server for AI, cheap device for doorbell
- ✅ **Scalability** - One LLM server can serve multiple doorbells
- ✅ **Easy upgrades** - Upgrade LLM server without touching doorbell device
- ✅ **Resource optimization** - GPU server can run other AI tasks too

## Network Setup

### LLM Server Configuration

**On the LLM server (192.168.1.100):**

1. **Install Vicuna:**
```bash
pip install "fschat[model_worker,webui]"
```

2. **Start FastChat server (accessible on network):**

```bash
# Terminal 1 - Controller
python -m fastchat.serve.controller --host 0.0.0.0

# Terminal 2 - Model Worker
python -m fastchat.serve.model_worker \
    --model-path lmsys/vicuna-13b-v1.5 \
    --num-gpus 1

# Terminal 3 - API Server (listen on all interfaces)
python -m fastchat.serve.openai_api_server \
    --host 0.0.0.0 \
    --port 8000
```

**Important:** Use `--host 0.0.0.0` to allow connections from other machines!

3. **Verify it's accessible:**
```bash
# On LLM server itself
curl http://localhost:8000/v1/models

# From another machine on network
curl http://192.168.1.100:8000/v1/models
```

### echoBell Device Configuration

**On echoBell "brains" device (192.168.1.50):**

1. **Edit config file** (`config/llm_config.toml`):
```toml
[llm.vicuna]
base_url = http://192.168.1.100:8000  # ← LLM server IP
model = vicuna-13b-v1.5
```

2. **Or use environment variable:**
```bash
export VICUNA_BASE_URL=http://192.168.1.100:8000
```

3. **Test connection:**
```python
from packages.llm.config_loader import load_llm_config

config = load_llm_config()
print(config['vicuna']['base_url'])
# Should print: http://192.168.1.100:8000
```

## Firewall Configuration

### LLM Server Firewall

Allow incoming connections on port 8000:

**Linux (Ubuntu/Debian):**
```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

**Windows:**
```powershell
# PowerShell (as Administrator)
New-NetFirewallRule -DisplayName "Vicuna API" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

**Router/Network:**
- No port forwarding needed (internal network only)
- Ensure both devices on same subnet (192.168.1.x)

## Performance Considerations

### Network Latency

- **Same subnet (gigabit):** ~1-5ms (negligible)
- **WiFi:** ~10-50ms (acceptable)
- **Cross-subnet:** May add routing delay

**Recommendation:** Use wired gigabit Ethernet for both devices if possible.

### Bandwidth Requirements

- **Request:** ~1-5 KB (prompt)
- **Response:** ~5-20 KB (generated text)
- **Per conversation:** ~50-200 KB total

**Typical usage:** <1 Mbps (well within gigabit capability)

### Latency Budget

```
Total response time: ~2-5 seconds

Breakdown:
- Audio transcription: 500ms
- Network to LLM: 5ms
- LLM generation: 1-3s
- Network from LLM: 5ms
- TTS generation: 800ms
```

Network adds <10ms, so not a bottleneck!

## High Availability Setup

### Option 1: LLM Server Redundancy

Run multiple LLM servers and load balance:

```python
# In config/llm_config.toml
[llm.vicuna]
base_urls = [
    "http://192.168.1.100:8000",  # Primary
    "http://192.168.1.101:8000"   # Backup
]
```

### Option 2: Health Checks

Add health monitoring to `VicunaClient`:

```python
async def _check_health(self):
    """Check if LLM server is alive"""
    try:
        async with self.session.get(
            f"{self.base_url}/v1/models",
            timeout=5
        ) as resp:
            return resp.status == 200
    except:
        return False
```

### Option 3: Fallback to Local

Keep a small model on echoBell device as fallback:

```python
llm_config = {
    "primary": {
        "base_url": "http://192.168.1.100:8000",
        "model": "vicuna-13b-v1.5"
    },
    "fallback": {
        "base_url": "http://localhost:8001",
        "model": "vicuna-7b-v1.5"  # Smaller, runs on echoBell device
    }
}
```

## Security Considerations

### Network Security

⚠️ **Important:** Vicuna API has no authentication by default!

**Options:**

1. **Firewall rules** (Recommended for home use):
   - Only allow connections from echoBell device IP
   ```bash
   # Linux
   sudo ufw allow from 192.168.1.50 to any port 8000
   ```

2. **VPN/VLAN** (Recommended for production):
   - Put LLM server and echoBell on isolated VLAN
   - No access from general network

3. **Reverse proxy with auth** (Advanced):
   ```nginx
   # nginx config
   location /v1/ {
       auth_basic "Restricted";
       auth_basic_user_file /etc/nginx/.htpasswd;
       proxy_pass http://localhost:8000;
   }
   ```

### Data Privacy

- ✅ All traffic stays on local network
- ✅ No data sent to cloud
- ✅ Doorbell audio processed locally
- ✅ Conversations stored in local database

## Monitoring & Debugging

### Check Connection from echoBell Device

```python
# Quick connection test
import aiohttp
import asyncio

async def test_connection():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                "http://192.168.1.100:8000/v1/models",
                timeout=5
            ) as resp:
                if resp.status == 200:
                    print("✅ LLM server reachable!")
                    data = await resp.json()
                    print(f"Available models: {data}")
                else:
                    print(f"❌ Server returned status: {resp.status}")
        except asyncio.TimeoutError:
            print("❌ Connection timeout - check firewall/network")
        except aiohttp.ClientConnectorError as e:
            print(f"❌ Connection refused - is server running? {e}")

asyncio.run(test_connection())
```

### Monitor Network Traffic

**On echoBell device:**
```bash
# Watch HTTP requests to LLM server
tcpdump -i eth0 host 192.168.1.100 and port 8000
```

**On LLM server:**
```bash
# Monitor incoming connections
netstat -an | grep :8000
```

### Log HTTP Requests

Enable verbose logging in `VicunaClient`:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Will show all HTTP requests/responses
```

## Troubleshooting

### Issue: "Connection refused"

**Check:**
1. Is LLM server running? `curl http://192.168.1.100:8000/v1/models`
2. Is firewall allowing port 8000?
3. Is FastChat bound to 0.0.0.0 (not 127.0.0.1)?

**Fix:**
```bash
# Restart FastChat with correct host binding
python -m fastchat.serve.openai_api_server --host 0.0.0.0 --port 8000
```

### Issue: "Connection timeout"

**Check:**
1. Can echoBell device ping LLM server? `ping 192.168.1.100`
2. Is there a router/firewall between them?
3. Are they on the same subnet?

**Fix:**
- Ensure both devices on same network (192.168.1.x)
- Check router settings

### Issue: "Slow responses"

**Check:**
1. Network latency: `ping 192.168.1.100`
2. LLM server GPU usage: `nvidia-smi`
3. Is LLM server overloaded?

**Fix:**
- Use gigabit Ethernet (not WiFi)
- Upgrade GPU or use smaller model
- Enable vLLM for faster inference

### Issue: "Random disconnections"

**Check:**
1. Network stability
2. LLM server uptime
3. FastChat logs for crashes

**Fix:**
- Add retry logic in VicunaClient
- Monitor with systemd (auto-restart)
- Use health checks

## Example Deployment

### Home Setup (Recommended)

```
Living Room:
  - echoBell device (Raspberry Pi 4)
  - IP: 192.168.1.50
  - Runs: Policy layer, ASR, TTS

Garage/Basement:
  - LLM server (Desktop with RTX 4090)
  - IP: 192.168.1.100
  - Runs: Vicuna via FastChat
  - Connected via gigabit Ethernet

Router:
  - DHCP reservations for both devices
  - Firewall rule: 192.168.1.50 → 192.168.1.100:8000
```

### Multi-Doorbell Setup

```
Devices:
  - Front Door echoBell: 192.168.1.51
  - Back Door echoBell: 192.168.1.52
  - Garage echoBell: 192.168.1.53

Shared:
  - LLM Server: 192.168.1.100
  - All doorbells connect to same LLM server
  - Load balanced automatically
```

## Next Steps

1. ✅ Set up LLM server with `--host 0.0.0.0`
2. ✅ Configure firewall rules
3. ✅ Update `config/llm_config.toml` with LLM server IP
4. ✅ Test connection: `python packages/llm/config_loader.py`
5. ✅ Run conversation example
6. ✅ Monitor network traffic during testing
7. ✅ Set up systemd service for auto-start

---

**Last Updated:** February 1, 2026  
**Recommended:** Gigabit Ethernet between devices
