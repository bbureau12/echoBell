# Integration Test: Unknown Vehicle → Telegram Alert

This integration test validates the complete flow from evidence detection to Telegram notification.

## Test Flow

```
Unknown Vehicle Evidence → Policy Evaluation → Telegram Alert → Verification
```

1. **Evidence Simulation**: Unknown white sedan detected (no trusted plate)
2. **Policy Matching**: Policy matches "unknown vehicle" condition
3. **Action Execution**: Telegram handler sends alert message
4. **Verification**: Check Telegram chat for actual message

---

## Prerequisites

### 1. Telegram Bot Setup

You need a Telegram bot token and chat ID:

**Get Bot Token**:
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Use `/newbot` command
3. Follow instructions
4. Save the token (e.g., `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

**Get Chat ID**:
1. Message [@userinfobot](https://t.me/userinfobot)
2. It will reply with your user ID
3. Save the ID (e.g., `123456789`)

### 2. Set Environment Variables

**Windows (PowerShell)**:
```powershell
$env:TELEGRAM_BOT_TOKEN = "your_bot_token_here"
$env:TELEGRAM_CHAT_ID = "your_chat_id_here"
```

**Linux/Mac**:
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
```

---

## Running the Test

### Option 1: Simple Standalone Script (Recommended)

```powershell
# Set environment variables first
$env:TELEGRAM_BOT_TOKEN = "your_token"
$env:TELEGRAM_CHAT_ID = "your_chat_id"

# Run the test
python tests/test_telegram_simple.py
```

**What it does**:
- Creates temporary test database
- Creates test policy (unknown vehicle → telegram)
- Simulates unknown vehicle evidence
- Evaluates policy and sends Telegram alert
- Shows detailed output
- Cleans up automatically

**Expected Output**:
```
✅ Created test database: test_integration.db
✅ Created test policy: 🧪 Test: Unknown Vehicle Alert

============================================================
🧪 INTEGRATION TEST: Unknown Vehicle → Telegram Alert
============================================================

✅ Telegram configured
   Bot Token: 1234567890:ABCdefG...
   Chat ID: 123456789

📊 Simulating evidence: Unknown white sedan detected
   - vision.vehicle_present = true (conf=0.95)
   - vision.color = white (conf=0.85)
   - vision.vehicle_type = sedan (conf=0.90)

📍 Context:
   Camera ID: 1
   Track Key: test_vehicle_123
   Event ID: test_event_001

🔄 Evaluating policies...

✅ 1 policy action(s) executed:

1. ✅ TELEGRAM
   Policy: 🧪 Test: Unknown Vehicle Alert
   Message: 🧪 TEST ALERT: Unknown white sedan detected at camera 1
   Priority: normal

✅ Alert logged to database (ID: 1)
   Type: telegram
   Priority: normal
   Success: Yes

============================================================
📱 TELEGRAM VERIFICATION
============================================================

Please check your Telegram chat for the test alert message.
Expected message: '🧪 TEST ALERT: Unknown white sedan detected at camera 1'
Chat ID: 123456789

✅ Integration test PASSED!

🧹 Cleaned up: test_integration.db
```

### Option 2: Pytest Integration Test

```powershell
# Set environment variables
$env:TELEGRAM_BOT_TOKEN = "your_token"
$env:TELEGRAM_CHAT_ID = "your_chat_id"

# Run pytest
pytest tests/test_integration_telegram.py -v -s
```

**What it does**:
- Runs multiple test scenarios
- Tests policy API directly
- Tests full HTTP API flow (requires policy-server running)
- More comprehensive but requires more setup

---

## Verification

After running the test, you should receive a Telegram message like:

```
🧪 TEST ALERT: Unknown white sedan detected at camera 1
```

**If you don't receive the message**, check:

1. **Environment variables set?**
   ```powershell
   echo $env:TELEGRAM_BOT_TOKEN
   echo $env:TELEGRAM_CHAT_ID
   ```

2. **Bot token valid?**
   - Test with: `https://api.telegram.org/bot<TOKEN>/getMe`

3. **Chat ID correct?**
   - Message [@userinfobot](https://t.me/userinfobot) again

4. **Bot started?**
   - Send `/start` to your bot in Telegram first

---

## Test with Policy Server (Full API Test)

For a complete end-to-end test using the policy server:

### 1. Start Policy Server

```powershell
# Terminal 1
cd apps/policy-server
python server.py
```

### 2. Send Evidence via API

```powershell
# Terminal 2
curl -X POST http://localhost:8000/evidence `
  -H "Content-Type: application/json" `
  -d '{
    "camera_id": 1,
    "event_id": "test_001",
    "timestamp": 1706112000,
    "objects": [{
      "object_id": 1,
      "cls": "vehicle",
      "raw_class": "car",
      "bbox": [100, 200, 300, 400],
      "props": {
        "color": "white",
        "scene_track_key": "test_vehicle"
      }
    }],
    "evidence": [
      {"source": "vision", "feature": "vehicle_present", "value": "true", "conf": 0.95},
      {"source": "vision", "feature": "color", "value": "white", "conf": 0.85},
      {"source": "vision", "feature": "vehicle_type", "value": "sedan", "conf": 0.90}
    ]
  }'
```

### 3. Check Server Logs

You should see:
```
[EVIDENCE] Received from camera 1, event test_001
  Objects: 1
  Evidence: 3 original + 0 movement
    - vision.vehicle_present = true (conf=0.95)
    - vision.color = white (conf=0.85)
    - vision.vehicle_type = sedan (conf=0.90)
  [POLICY] Executed 1 actions:
    ✓ telegram - 🧪 Test: Unknown Vehicle Alert
```

### 4. Check Telegram

You should receive the alert message in your Telegram chat.

---

## Troubleshooting

### "No policies matched"

**Problem**: Policy didn't match the evidence.

**Solution**: Check policy conditions in database:
```sql
sqlite3 test_integration.db
SELECT id, name, conditions_json FROM policy_rules;
```

Ensure conditions match the evidence you're sending.

### "Telegram not configured"

**Problem**: Environment variables not set.

**Solution**:
```powershell
$env:TELEGRAM_BOT_TOKEN = "your_token"
$env:TELEGRAM_CHAT_ID = "your_chat_id"
```

### "Telegram action failed"

**Problem**: Bot token or chat ID invalid.

**Solution**: Test manually:
```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage \
  -d chat_id=<YOUR_CHAT_ID> \
  -d text="Test message"
```

### Message not received

**Possible causes**:
1. Bot blocked by user → Unblock and send `/start`
2. Wrong chat ID → Check with @userinfobot
3. Network issues → Check firewall/proxy
4. Bot token expired → Create new bot

---

## Cleanup

The simple test cleans up automatically. For manual cleanup:

```powershell
# Remove test database
Remove-Item test_integration.db

# Clear environment variables (optional)
Remove-Item Env:\TELEGRAM_BOT_TOKEN
Remove-Item Env:\TELEGRAM_CHAT_ID
```

---

## Next Steps

Once the basic test works:

1. **Create real policies** via API or YAML
2. **Test with actual edge devices** sending real evidence
3. **Add custom action handlers** (SMS, email, webhooks)
4. **Monitor alert_history** for audit trail
5. **Tune policy priorities** and conditions

See:
- [POLICY_API.md](../docs/POLICY_API.md) - Policy management API
- [ACTION_HANDLERS.md](../docs/ACTION_HANDLERS.md) - Custom actions
- [POLICY_REFERENCE.md](../docs/POLICY_REFERENCE.md) - Condition operators
