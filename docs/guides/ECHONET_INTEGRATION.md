# Echonet Auto-Discovery & Registration

## Overview

The policy server automatically discovers and registers with Echonet instances on the local network using mDNS/Zeroconf.

## Features

- **Auto-Discovery**: Finds Echonet instances broadcasting `_echonet._tcp.local.`
- **Auto-Registration**: Registers policy server as "echobell" target
- **Health Checks**: Periodically verifies registration status
- **Re-registration**: Automatically re-registers if connection lost
- **Error Reporting**: Logs warnings for failed registrations

## Configuration

### Environment Variables

```bash
# Echonet target registration
ECHONET_TARGET_NAME=echobell             # Default: "echobell"
ECHONET_WAKE_PHRASES=echobell           # Default: "echobell" (comma-separated)
ECHONET_API_KEY=dontgiveitupluffy        # Default: "dontgiveitupluffy"
POLICY_SERVER_BASE_URL=http://policy-server.local:8000  # Required!

# Database (existing)
ECHOBELL_DB_PATH=data/echoBell.db
```

### Important: Set Your Base URL

The policy server needs to know its public/network-accessible URL:

```bash
# Good examples
export POLICY_SERVER_BASE_URL=http://192.168.1.100:8000
export POLICY_SERVER_BASE_URL=http://policy-server.local:8000
export POLICY_SERVER_BASE_URL=http://echobell-server:8000

# Bad examples (won't work from Echonet)
export POLICY_SERVER_BASE_URL=http://localhost:8000  # ❌ Echonet can't reach localhost
export POLICY_SERVER_BASE_URL=http://127.0.0.1:8000  # ❌ Same problem
```

## Installation

### Install Zeroconf

```bash
pip install zeroconf>=0.132
```

Or add to your requirements:
```
zeroconf>=0.132
```

## How It Works

### 1. **Startup Discovery**

When policy server starts:
1. Initializes mDNS listener for `_echonet._tcp.local.`
2. Discovers all Echonet instances on network
3. Registers with each instance as "echobell"
4. Logs success/failure for each

### 2. **Runtime Discovery**

While running:
- New Echonet instances that come online are auto-discovered
- Automatically registers with newly discovered instances
- Logs when instances go offline

### 3. **Health Checks**

The `/health` endpoint:
- Verifies registration with all discovered instances
- Re-registers if connection was lost
- Returns detailed status

## API Endpoints

### GET `/health`

Health check with Echonet status and auto re-registration.

**Response:**
```json
{
  "status": "healthy",
  "database": "data/echoBell.db",
  "scene_tracker": {...},
  "echonet": {
    "discovery_enabled": true,
    "discovered_count": 2,
    "registered_count": 2,
    "failed_count": 0,
    "instances": [
      {
        "instance": "Echonet Main Floor zone:home subzone:main-floor",
        "status": "registered",
        "url": "http://192.168.1.50:8123"
      },
      {
        "instance": "Echonet Bedroom zone:home subzone:bedroom",
        "status": "registered",
        "url": "http://192.168.1.51:8123"
      }
    ],
    "timestamp": "2026-02-02T10:30:00"
  }
}
```

### GET `/admin/echonet/status`

Get detailed Echonet registration status (no re-registration).

**Response:**
```json
{
  "discovery_enabled": true,
  "discovered_count": 2,
  "registered_count": 2,
  "failed_count": 0,
  "instances": [
    {
      "name": "Echonet Main Floor zone:home subzone:main-floor",
      "url": "http://192.168.1.50:8123",
      "zone": "home",
      "subzone": "main-floor",
      "registered": true,
      "error": null
    }
  ]
}
```

### POST `/admin/echonet/register`

Manually trigger registration for all discovered instances.

**Use case**: Force re-registration after network issues.

**Response:**
```json
{
  "message": "Registration attempted for all discovered instances",
  "result": {
    "discovered_count": 2,
    "registered_count": 2,
    "instances": [...]
  }
}
```

## Testing

### 1. Check Discovery

```bash
# Start policy server
uvicorn server:app --reload

# Check logs for:
# [info] Echonet discovery started (target: echobell, phrases: echobell)
# Discovered Echonet: Echonet Main Floor zone:home subzone:main-floor at http://192.168.1.50:8123
# ✓ Registered with Echonet: Echonet Main Floor (wake phrases: echobell)
```

### 2. Verify Registration

```bash
# Check policy server health
curl http://localhost:8000/health | jq .echonet

# Check Echonet directly
curl http://192.168.1.50:8123/targets/echobell \
  -H "X-API-Key: dontgiveitupluffy"

# Expected response:
{
  "name": "echobell",
  "base_url": "http://policy-server.local:8000",
  "phrases": ["echobell"],
  "listen_url": "http://policy-server.local:8000/voice/listen"
}
```

### 3. Test Voice Command

Speak near Echonet microphone:
```
"Echobell, who is at the door?"
```

Check policy server logs:
```
[echo-1738449600-abc123] Received voice event: who is at the door from alice
```

## Troubleshooting

### No Instances Discovered

**Symptom**: `discovered_count: 0`

**Solutions**:
1. **Check Echonet is broadcasting**:
   ```bash
   # On macOS/Linux
   dns-sd -B _echonet._tcp
   
   # Or use avahi-browse (Linux)
   avahi-browse -r _echonet._tcp
   ```

2. **Install zeroconf**:
   ```bash
   pip install zeroconf
   ```

3. **Check network**:
   - Echonet and policy server on same network/VLAN?
   - Firewall blocking mDNS (port 5353)?
   - mDNS enabled on network?

### Registration Failed

**Symptom**: `failed_count > 0` in health check

**Solutions**:
1. **Check base URL**:
   ```bash
   # From Echonet host, test connectivity
   curl http://policy-server.local:8000/health
   ```
   If this fails, Echonet can't reach policy server.

2. **Check API key**:
   ```bash
   # Verify API key matches
   echo $ECHONET_API_KEY
   # Should be: dontgiveitupluffy (or your custom key)
   ```

3. **Check Echonet API**:
   ```bash
   # Test Echonet registration endpoint
   curl -X POST http://192.168.1.50:8123/register \
     -H "X-API-Key: dontgiveitupluffy" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "test",
       "base_url": "http://test:9000",
       "phrases": ["test"]
     }'
   ```

### Zeroconf Not Available

**Symptom**: 
```
[warning] zeroconf not installed. Echonet auto-discovery disabled.
```

**Solution**:
```bash
pip install zeroconf
```

### Registration Lost After Network Change

**Symptom**: Was registered, now shows as failed

**Solutions**:
1. **Health check will auto re-register**:
   ```bash
   curl http://localhost:8000/health
   ```

2. **Manual re-registration**:
   ```bash
   curl -X POST http://localhost:8000/admin/echonet/register
   ```

3. **Restart policy server** (re-discovers and re-registers)

## Monitoring

### Health Check Polling

Set up periodic health checks to maintain registrations:

```bash
# Cron job (every 5 minutes)
*/5 * * * * curl -s http://localhost:8000/health > /dev/null
```

Or use a monitoring tool:
```python
import asyncio
import httpx

async def health_check_loop():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/health")
                data = response.json()
                
                if data.get("echonet", {}).get("failed_count", 0) > 0:
                    print("⚠️  Some Echonet registrations failed!")
                    # Send alert to Telegram (future)
        except Exception as e:
            print(f"Health check failed: {e}")
        
        await asyncio.sleep(300)  # 5 minutes

asyncio.run(health_check_loop())
```

### Check Logs

Look for registration events:
```bash
# Successful registration
grep "Registered with Echonet" logs/policy-server.log

# Failed registrations  
grep "Failed to register with" logs/policy-server.log

# Discovery events
grep "Discovered Echonet" logs/policy-server.log
```

## Advanced Configuration

### Multiple Wake Phrases

```bash
export ECHONET_WAKE_PHRASES="echobell,hey echo,echo bell"
```

Users can say any of:
- "Echobell, turn on the lights"
- "Hey Echo, who's at the door?"
- "Echo Bell, what's the temperature?"

### Custom Target Name

```bash
export ECHONET_TARGET_NAME=my-home-assistant
```

Registers as "my-home-assistant" instead of "echobell".

### Custom API Key

```bash
export ECHONET_API_KEY=my-secure-key-123
```

Must match Echonet's configured API key.

## Integration with Voice Commands

Once registered, Echonet will POST to `/voice/listen` when wake word is detected:

```
User says: "Echobell, who is at the door?"
    ↓
Echonet detects "echobell" wake phrase
    ↓
Echonet POSTs to http://policy-server.local:8000/voice/listen
    ↓
Policy server processes: "who is at the door"
    ↓
Returns response for TTS
```

See `VOICE_COMMAND_SUMMARY.md` for voice command processing details.

## Example: Full Setup

```bash
# 1. Install dependencies
pip install zeroconf httpx fastapi uvicorn

# 2. Set environment variables
export POLICY_SERVER_BASE_URL=http://192.168.1.100:8000
export ECHONET_API_KEY=dontgiveitupluffy
export ECHONET_WAKE_PHRASES=echobell

# 3. Start policy server
cd central/policy-server
uvicorn server:app --host 0.0.0.0 --port 8000

# 4. Verify discovery (check logs)
# [info] Echonet discovery started
# Discovered Echonet: Echonet Main Floor at http://192.168.1.50:8123
# ✓ Registered with Echonet: Echonet Main Floor

# 5. Test health
curl http://localhost:8000/health | jq .echonet

# 6. Test voice command
# Speak: "Echobell, test command"
```

## Files

- `central/policy-server/echonet_service.py` - Discovery and registration service
- `central/policy-server/server.py` - Integration with FastAPI
- `docs/ECHONET_INTEGRATION.md` - This file

## See Also

- Voice Command Integration: `docs/VOICE_COMMAND_SUMMARY.md`
- Voice Quick Reference: `docs/VOICE_QUICKREF.md`
- Echonet Documentation: Upstream Echonet project
