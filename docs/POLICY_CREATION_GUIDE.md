# Policy Creation Guide

Complete guide to creating and managing policies in the EchoBell system.

## Table of Contents
- [Quick Start](#quick-start)
- [Policy Structure](#policy-structure)
- [Condition Reference](#condition-reference)
- [Variable System](#variable-system)
- [Action Reference](#action-reference)
- [Common Patterns](#common-patterns)
- [Testing Policies](#testing-policies)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Minimal Policy Template

```json
{
  "id": "my_policy",
  "name": "My Policy Name",
  "description": "What this policy does",
  "enabled": 1,
  "priority": 50,
  "conditions": {
    "all": [
      {"camera_id_eq": 1},
      {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}}
    ]
  },
  "actions": [
    {
      "type": "telegram",
      "message": "🚗 Vehicle detected: {vehicle_color} {vehicle_type}",
      "priority": "normal"
    }
  ]
}
```

### Adding Policy to Database

**Option 1: SQL Migration**
```sql
-- Create file: infra/db/migrations/0XX_add_my_policy.sql
INSERT INTO policy_rules (
    id, name, description, enabled, priority,
    conditions_json, actions_json,
    created_ts, updated_ts
) VALUES (
    'my_policy',
    'My Policy Name',
    'Description here',
    1,
    50,
    '{"all": [{"camera_id_eq": 1}]}',
    '[{"type": "telegram", "message": "Alert!"}]',
    strftime('%s', 'now'),
    strftime('%s', 'now')
);
```

**Option 2: Python Script**
```python
import sqlite3
import json

conn = sqlite3.connect('data/echoBell.db')

policy = {
    "id": "my_policy",
    "name": "My Policy",
    "enabled": 1,
    "priority": 50,
    "conditions": {"all": [...]},
    "actions": [...]
}

conn.execute("""
    INSERT INTO policy_rules 
    (id, name, description, enabled, priority, conditions_json, actions_json, created_ts, updated_ts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    policy['id'],
    policy['name'],
    policy.get('description', ''),
    policy['enabled'],
    policy['priority'],
    json.dumps(policy['conditions']),
    json.dumps(policy['actions']),
    int(time.time()),
    int(time.time())
))

conn.commit()
conn.close()
```

---

## Policy Structure

### Complete Policy Object

```json
{
  "id": "unique_policy_id",           // Required: unique identifier
  "name": "Human Readable Name",       // Required: display name
  "description": "What it does",       // Optional: detailed description
  "enabled": 1,                        // Required: 1=active, 0=disabled
  "priority": 85,                      // Required: higher = evaluated first
  "conditions": {                      // Required: see Condition Reference
    "all": [...]                       // or "any": [...]
  },
  "actions": [...],                    // Required: see Action Reference
  "variables": {...},                  // Optional: custom variable definitions
  "tags": "vehicle alert",             // Optional: space-separated tags
  "created_by": "system",              // Optional: who created it
  "version": 1                         // Optional: for versioning
}
```

### Priority System

Policies are evaluated in **priority order (highest first)**:
- **100+**: Critical/override policies (trusted person checks)
- **80-99**: High priority alerts (security, unknown visitors)
- **50-79**: Normal alerts (routine notifications)
- **20-49**: Low priority (informational)
- **1-19**: Fallback/catch-all policies

**Note:** ALL matching policies execute (not just highest priority). Use conditions to prevent conflicts.

---

## Condition Reference

Conditions determine WHEN a policy triggers. All conditions must evaluate to `true` for the policy to match.

### Logical Operators

```json
// ALL conditions must match (AND)
{"all": [condition1, condition2, ...]}

// ANY condition must match (OR)  
{"any": [condition1, condition2, ...]}

// NONE of the conditions match (NOT)
{"none": [condition1, condition2, ...]}
```

### Camera Filters

```json
// Match specific camera
{"camera_id_eq": 1}

// Match any camera in list
{"camera_id_in": [1, 2, 3]}
```

**Example:**
```json
{
  "all": [
    {"camera_id_eq": 1},  // Only camera 1
    // ... other conditions
  ]
}
```

### Evidence Checks

```json
// Evidence exists (feature present)
{
  "evidence_exists": {
    "source": "vision",
    "feature": "vehicle_present"
  }
}

// Evidence missing (feature not present)
{
  "evidence_missing": {
    "source": "plate_trust",
    "feature": "trusted_plate"
  }
}

// Evidence value equals
{
  "evidence_value_eq": {
    "source": "vision",
    "feature": "vehicle_type",
    "value": "truck"
  }
}

// Evidence value greater than
{
  "evidence_value_gt": {
    "source": "vision",
    "feature": "confidence",
    "value": 0.8
  }
}

// Evidence value less than
{
  "evidence_value_lt": {
    "source": "vision",
    "feature": "distance",
    "value": 10
  }
}
```

**Common Evidence Sources:**
- `vision` - Object detection (vehicle_present, person_present, color, etc.)
- `ocr` - Text recognition (plate_text, sign_text)
- `plate_trust` - Plate trust lookups (trusted_plate)
- `scene` - Scene tracking (vehicle_entered, person_exited, loitering)
- `audio` - Audio analysis (transcript, voice_command)

### Time-Based Conditions

```json
// Track duration (how long object has been present)
{
  "track_duration_gt": 300  // Greater than 5 minutes (seconds)
}

{
  "track_duration_lt": 60   // Less than 1 minute
}

// Time of day
{
  "time_between": {
    "start": "22:00",        // 24-hour format
    "end": "06:00"          // Wraps midnight
  }
}

// Day of week
{
  "day_of_week": ["Saturday", "Sunday"]
}
```

### Alert Control (Spam Prevention)

```json
// No recent alert sent (cooldown)
{
  "no_recent_alert": {
    "track_type": "vehicle",     // person, vehicle, etc.
    "within_seconds": 300        // 5 minutes
  }
}

// Alert WAS sent recently
{
  "alert_sent_within": {
    "track_type": "person",
    "within_seconds": 600        // 10 minutes
  }
}
```

**Important:** Requires `alert_history` table (migration 010).

### Trust/Identity Checks

```json
// Check if trusted person
{
  "trust_check": {
    "check_type": "trusted_person"
  }
}

// Check if trusted vehicle
{
  "trust_check": {
    "check_type": "trusted_vehicle"
  }
}
```

### Event Type Filters

```json
// Match specific event type
{
  "event_type": {
    "equals": "voice_command"
  }
}
```

---

## Variable System

Variables allow dynamic content in action messages. They are automatically extracted from evidence and context.

### Auto-Extracted Variables from Evidence

When evidence contains these features, they become variables:

| Evidence Feature | Variable | Example |
|---|---|---|
| `vehicle_color` | `{vehicle_color}` | "white" |
| `vehicle_type` | `{vehicle_type}` | "sedan" |
| `color` | `{color}` | "red" |
| `plate_text` | `{plate_text}` | "ABC123" |
| `person_name` | `{person_name}` | "John Doe" |
| `latest_frame_path` | `{latest_frame_path}` | "data/img.jpg" |
| `visitor_id` | `{visitor_id}` | "vis_123" |
| `intent` | `{intent}` | "unlock_door" |
| `confidence` | `{confidence}` | "0.95" |

**Plus: Generic Pattern**
ALL evidence creates `{source}_{feature}` variables:
```json
// Evidence:
{"source": "vision", "feature": "bbox", "value": "[100,200,50,50]"}

// Creates variable:
{vision_bbox} = "[100,200,50,50]"
```

### Context Variables

Automatically available from the evaluation context:

| Variable | Description | Example |
|---|---|---|
| `{camera_id}` | Camera identifier | "1" |
| `{track_key}` | Track identifier | "vehicle_abc123" |
| `{track_type}` | Track type | "person", "vehicle" |
| `{event_id}` | Event identifier | "evt_123" |
| `{timestamp}` | Unix timestamp | "1739200000" |

### Using Variables in Actions

```json
{
  "type": "telegram",
  "message": "Camera {camera_id}: {vehicle_color} {vehicle_type} detected",
  "photo_path": "{latest_frame_path}"
}
```

**Output Example:**
```
Camera 1: white sedan detected
[photo attached]
```

### Custom Variables (Advanced)

Define variables in the policy:

```json
{
  "variables": {
    "location_name": {
      "lookup": {
        "table": "cameras",
        "match_field": "id",
        "return_field": "location"
      }
    }
  },
  "actions": [{
    "type": "telegram",
    "message": "Alert at {location_name}"
  }]
}
```

---

## Action Reference

Actions define WHAT happens when a policy matches.

### Telegram Action

Send a message to Telegram (with optional photo).

```json
{
  "type": "telegram",
  "message": "Your message with {variables}",
  "priority": "normal",           // Optional: "low", "normal", "urgent"
  "send_photo": true,              // Optional: attach a photo
  "photo_path": "{snapshot_path}"  // Required if send_photo=true
}
```

**Photo Path in Production vs Testing:**

In **production** with edge devices:
- Edge agent captures frame and saves locally (e.g., `/edge/images/cam1_123456.jpg`)
- Edge agent starts HTTP server to serve images
- Edge sends `snapshot_url` in request: `"http://192.168.1.100:8080/cam1_123456.jpg"`
- Policy server should download image before sending to Telegram
- Use `{snapshot_url}` variable in policy *(implementation needed)*

In **testing** (same machine):
- Test script includes local file path in context
- Policy can access file directly
- Use `{snapshot_path}` variable from context

**Current Implementation:**
- Policies use `{snapshot_path}` from request context
- Works for single-machine testing
- **TODO**: Add snapshot URL download support for distributed edge devices

**Photo Requirements:**
- Supported formats: JPG, PNG
- Max size: 10MB (Telegram limit)
- File must be readable by policy server process

**Example: Text Only**
```json
{
  "type": "telegram",
  "message": "⚠️ Unknown {vehicle_color} {vehicle_type} detected",
  "priority": "urgent"
}
```

**Example: With Photo (Testing)**
```json
{
  "type": "telegram",
  "message": "🚗 Vehicle on Camera {camera_id}",
  "send_photo": true,
  "photo_path": "{snapshot_path}"  // From request context
}
```

### Speak Action

Use text-to-speech (requires TTS integration).

```json
{
  "type": "speak",
  "text": "Message to speak. Can include {variables}."
}
```

**Example:**
```json
{
  "type": "speak",
  "text": "Warning: You have been loitering for {duration_minutes} minutes. Please leave."
}
```

### Webhook Action

Send HTTP POST to external service.

```json
{
  "type": "webhook",
  "url": "https://example.com/webhook",
  "payload": {
    "camera_id": "{camera_id}",
    "event_type": "vehicle_detected",
    "vehicle": "{vehicle_color} {vehicle_type}"
  }
}
```

### Create Watch Action

Schedule deferred policy evaluation (advanced).

```json
{
  "type": "create_watch",
  "watch_type": "loitering_5min",
  "due_in_seconds": 300
}
```

**Example: Escalation Chain**
```json
// Policy 1: Initial detection
{
  "conditions": {...},
  "actions": [{
    "type": "create_watch",
    "watch_type": "check_still_present",
    "due_in_seconds": 120  // Check again in 2 minutes
  }]
}

// Policy 2: Triggered by watch
{
  "conditions": {
    "all": [
      {"evidence_exists": {"source": "watch", "value": "check_still_present"}},
      {"evidence_exists": {"source": "scene", "feature": "person_present"}}
    ]
  },
  "actions": [{
    "type": "telegram",
    "message": "Person still present after 2 minutes!"
  }]
}
```

---

## Common Patterns

### Pattern: Vehicle Detection with Photo

```json
{
  "id": "cam1_vehicle_photo",
  "name": "Camera 1 - Vehicle with Photo",
  "enabled": 1,
  "priority": 80,
  "conditions": {
    "all": [
      {"camera_id_eq": 1},
      {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}}
    ]
  },
  "actions": [{
    "type": "telegram",
    "message": "🚗 {vehicle_color} {vehicle_type} detected on Camera {camera_id}",
    "send_photo": true,
    "photo_path": "{latest_frame_path}"
  }]
}
```

### Pattern: Unknown Vehicle Alert

```json
{
  "id": "unknown_vehicle",
  "name": "Unknown Vehicle Alert",
  "enabled": 1,
  "priority": 85,
  "conditions": {
    "all": [
      {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
      {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}}
    ]
  },
  "actions": [{
    "type": "telegram",
    "message": "⚠️ Unknown vehicle: {vehicle_color} {vehicle_type}",
    "priority": "urgent"
  }]
}
```

### Pattern: Loitering Detection with Cooldown

```json
{
  "id": "loitering_alert",
  "name": "Loitering Alert",
  "enabled": 1,
  "priority": 75,
  "conditions": {
    "all": [
      {"evidence_exists": {"source": "scene", "feature": "person_present"}},
      {"track_duration_gt": 300},  // 5 minutes
      {"no_recent_alert": {
        "track_type": "person",
        "within_seconds": 600  // Don't spam (10 min cooldown)
      }}
    ]
  },
  "actions": [
    {
      "type": "telegram",
      "message": "⚠️ Person loitering for {duration_minutes} minutes"
    },
    {
      "type": "speak",
      "text": "You are being recorded. Please leave the premises."
    }
  ]
}
```

### Pattern: Nighttime Security

```json
{
  "id": "nighttime_person",
  "name": "Nighttime Person Detection",
  "enabled": 1,
  "priority": 90,
  "conditions": {
    "all": [
      {"evidence_exists": {"source": "vision", "feature": "person_present"}},
      {"time_between": {"start": "22:00", "end": "06:00"}}
    ]
  },
  "actions": [{
    "type": "telegram",
    "message": "🌙 Person detected at night on Camera {camera_id}",
    "priority": "urgent",
    "send_photo": true,
    "photo_path": "{latest_frame_path}"
  }]
}
```

### Pattern: Trusted Person (Quiet Entry)

```json
{
  "id": "trusted_quiet",
  "name": "Trusted Person - No Alert",
  "enabled": 1,
  "priority": 100,  // Highest priority
  "conditions": {
    "all": [
      {"evidence_exists": {"source": "vision", "feature": "person_present"}},
      {"trust_check": {"check_type": "trusted_person"}}
    ]
  },
  "actions": [{
    "type": "telegram",
    "message": "🏠 {person_name} arrived home",
    "priority": "low"  // Low priority = quiet notification
  }]
}
```

### Pattern: Delivery Timeout

```json
{
  "id": "delivery_timeout",
  "name": "Expected Delivery Timeout",
  "enabled": 1,
  "priority": 60,
  "conditions": {
    "all": [
      {"evidence_exists": {"source": "scheduled_event", "feature": "delivery_window"}},
      {"evidence_missing": {"source": "vision", "feature": "package_present"}}
    ]
  },
  "actions": [{
    "type": "telegram",
    "message": "📦 Delivery window ended - no package detected"
  }]
}
```

---

## Testing Policies

You have three main ways to test policies: standalone evaluation, direct API testing, and integration testing.

### Method 1: Standalone Policy Test (Fastest)

Best for quick testing without running the full API server.

```python
# tests/test_my_policy.py
import sqlite3
import asyncio
import time
from packages.policy.apply import evaluate_policies

# Define test evidence (matches what vision.py produces)
evidence = [
    # Scene-level evidence
    {
        'source': 'vision',
        'feature': 'vehicle_present',
        'value': 'true',
        'conf': 0.95,
        'object_id': None  # Scene-level
    },
    # Object-level evidence (from YOLO detection)
    {
        'source': 'vision',
        'feature': 'class',
        'value': 'vehicle',
        'conf': 0.95,
        'object_id': 1
    },
    {
        'source': 'vision',
        'feature': 'vehicle_type',
        'value': 'car',  # raw_class from YOLO
        'conf': 0.90,
        'object_id': 1
    },
    {
        'source': 'vision',
        'feature': 'color',
        'value': 'white',
        'conf': 0.60,  # Color detection is less confident
        'object_id': 1
    }
]

# Define context (from edge agent)
context = {
    'camera_id': 1,
    'track_key': 'test_vehicle_123',
    'track_type': 'vehicle',
    'event_id': 'test_event_001',
    'timestamp': int(time.time()),
    'snapshot_path': 'data/edge_images/test_image.jpg'  # For photo policies
}

# Run evaluation
async def test():
    conn = sqlite3.connect('data/echoBell.db')
    
    try:
        results = await evaluate_policies(
            evidence=evidence,
            context=context,
            conn=conn,
            use_database=True
        )
        
        print(f"Policies triggered: {len(results)}")
        for result in results:
            print(f"  - {result.get('policy_name')}: {result.get('success')}")
            
    finally:
        conn.close()

asyncio.run(test())
```

**Run:**
```powershell
python tests/test_my_policy.py
```

**Check Results:**
- ✅ Policy matched and executed
- ✅ Telegram message sent (check chat)
- ✅ Photo attached (if applicable)
- ✅ Variables substituted correctly

---

### Method 2: API Integration Test (Recommended)

Test through the actual API server for full end-to-end validation.

#### Step 1: Start the Policy API Server

In **Terminal 1**:
```powershell
cd central/policy-server
python server.py
```

You should see:
```
[info] Watch worker started
INFO:     Started server process [12345]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Keep this terminal open!**

#### Step 2: Send Test Request

In **Terminal 2** (or use a test script):

**Option A: Use Test Script** (Recommended)
```python
# examples/send_test_request.py
import requests
import time

def send_test_evidence():
    """Send test vehicle evidence to policy API"""
    
    # Construct full evidence payload
    # NOTE: In production, the edge agent sends this automatically
    payload = {
        'camera_id': 1,
        'event_id': f'test_evt_{int(time.time())}',
        'timestamp': int(time.time()),
        'objects': [{
            'object_id': 1,
            'label': 'vehicle',
            'bbox': [100, 200, 400, 400],
            'props': {
                'scene_track_key': 'vehicle_test_123',
                'vehicle_color': 'white',
                'vehicle_type': 'sedan',
                'raw_class': 'car'
            }
        }],
        'evidence': [
            {
                'source': 'vision',
                'feature': 'vehicle_present',
                'value': 'true',
                'conf': 0.95,
                'object_id': None  # Scene-level evidence
            },
            {
                'source': 'vision',
                'feature': 'class',
                'value': 'vehicle',
                'conf': 0.95,
                'object_id': 1  # Object-level evidence
            },
            {
                'source': 'vision',
                'feature': 'vehicle_type',
                'value': 'car',
                'conf': 0.90,
                'object_id': 1
            },
            {
                'source': 'vision',
                'feature': 'color',
                'value': 'white',
                'conf': 0.60,
                'object_id': 1
            }
        ]
    }
    
    # **IMPORTANT**: Photo path handling
    # In production, the edge agent includes a snapshot_url in the request:
    #   payload["snapshot_url"] = "http://edge-device:8080/cam1_123456.jpg"
    # The policy server would need to download this image first.
    # 
    # For testing, we simulate a local image file instead:
    if 'context' not in payload:
        payload['context'] = {}
    payload['context']['snapshot_path'] = 'data/edge_images/test_frame.jpg'
    
    # Send request
    try:
        response = requests.post('http://localhost:8000/evidence', json=payload, timeout=10)
        response.raise_for_status()
        
        print("✅ Evidence submitted successfully!")
        print(f"Response: {response.json()}")
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server. Is it running?")
        print("   Start server: cd central/policy-server && python server.py")
    except requests.exceptions.Timeout:
        print("⚠️  Request timed out")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    send_test_evidence()
```

**Run:**
```powershell
python examples/send_test_request.py
```

**Option B: Direct curl/PowerShell**

This example shows a realistic payload similar to what the **edge agent** sends:

```powershell
# PowerShell - Simulates edge agent request
$body = @{
    camera_id = 1
    event_id = "evt_$(Get-Date -UFormat %s)_1"
    timestamp = [int][double]::Parse((Get-Date -UFormat %s))
    event_type = "detection"
    
    # Objects detected by YOLO vision
    objects = @(
        @{
            object_id = 1
            label = "vehicle"
            bbox = @(100, 200, 400, 400)
            confidence = 0.95
            props = @{
                raw_class = "car"        # Original YOLO class
                color = "white"          # Detected color
                conf = 0.95
            }
        }
    )
    
    # Evidence from vision system (automatically generated)
    evidence = @(
        # Scene-level evidence (object_id=null)
        @{source = "vision"; feature = "vehicle_present"; value = "true"; conf = 0.95; object_id = $null},
        
        # Object-level evidence
        @{source = "vision"; feature = "class"; value = "vehicle"; conf = 0.95; object_id = 1},
        @{source = "vision"; feature = "vehicle_type"; value = "car"; conf = 0.90; object_id = 1},
        @{source = "vision"; feature = "color"; value = "white"; conf = 0.60; object_id = 1}
    )
    
    # Context from edge agent
    context = @{
        mode = "passive"              # "doorbell" or "passive"
        person_present = $false
        vehicle_present = $true
        source = "camera_1"
        snapshot_path = "data/edge_images/test_frame.jpg"  # For testing (same machine)
        # snapshot_url = "http://192.168.1.100:8080/cam1_123456.jpg"  # Production (edge device)
    }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/evidence" -Method POST -Body $body -ContentType "application/json"
```

**Note:** The edge agent does NOT send `latest_frame_path` as evidence. It sends `snapshot_path` in the context or `snapshot_url` for remote edge devices.

#### Step 3: Check Server Logs

In **Terminal 1** (server), look for:
```
[POLICY] Matched policy: camera1_vehicle_with_photo
[TELEGRAM] Attempting to send photo: data/edge_images/test_frame.jpg
[TELEGRAM] NORMAL: 🚗 Vehicle detected on Camera 1: white sedan - ✓
```

#### Step 4: Verify Results

- ✅ Check Telegram for message and photo
- ✅ Verify variables substituted correctly
- ✅ Test cooldown (send again within 30 seconds - should be blocked)

---

### Method 3: Complete API Test Suite

For comprehensive testing with cooldown and health checks:

```python
# tests/test_camera1_vehicle_api.py
import requests
import time

API_URL = "http://localhost:8000"

def check_health():
    """Check if API server is running"""
    try:
        response = requests.get(f"{API_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def send_vehicle_evidence():
    """Send vehicle detection evidence"""
    payload = {
        'camera_id': 1,
        'event_id': f'test_{int(time.time())}',
        'timestamp': int(time.time()),
        'objects': [{
            'object_id': 1,
            'label': 'vehicle',
            'bbox': [100, 200, 400, 400],
            'props': {'vehicle_color': 'white', 'vehicle_type': 'sedan'}
        }],
        'evidence': [
            {'source': 'vision', 'feature': 'vehicle_present', 'value': 'true', 'conf': 0.95},
            {'source': 'vision', 'feature': 'vehicle_color', 'value': 'white', 'conf': 0.85},
            {'source': 'vision', 'feature': 'latest_frame_path', 
             'value': 'data/edge_images/test.jpg', 'conf': 1.0}
        ]
    }
    
    response = requests.post(f"{API_URL}/evidence", json=payload)
    return response

def main():
    print("=== Testing Camera 1 Vehicle Detection Policy ===\n")
    
    # 1. Health check
    print("1. Checking server health...")
    if not check_health():
        print("❌ Server not running! Start with: cd central/policy-server && python server.py")
        return
    print("✅ Server is running\n")
    
    # 2. First request (should trigger)
    print("2. Sending first vehicle detection...")
    response = send_vehicle_evidence()
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}\n")
    
    # 3. Immediate second request (should be blocked by cooldown)
    print("3. Testing cooldown (sending immediately after)...")
    response = send_vehicle_evidence()
    print(f"   Status: {response.status_code}")
    print(f"   Should not trigger alert due to 30s cooldown\n")
    
    # 4. Wait and retry
    print("4. Waiting 31 seconds for cooldown to expire...")
    time.sleep(31)
    
    print("5. Sending after cooldown...")
    response = send_vehicle_evidence()
    print(f"   Status: {response.status_code}")
    print(f"   Should trigger alert again\n")
    
    print("✅ Test complete! Check Telegram for messages.")

if __name__ == '__main__':
    main()
```

**Run:**
```powershell
python tests/test_camera1_vehicle_api.py
```

---

## Troubleshooting

### Policy Not Triggering

**Symptom:** Policy exists but never fires.

**Check:**

1. **Is policy enabled?**
   ```sql
   SELECT id, name, enabled FROM policy_rules WHERE id = 'my_policy';
   ```
   Should show `enabled = 1`

2. **Are conditions matching?**
   - Add debug logging to see which conditions fail
   - Check evidence features EXACTLY match condition requirements
   - Verify camera_id in context matches policy

3. **Correct condition syntax?**
   ```json
   // ❌ WRONG
   {"camera_id": {"equals": 1}}
   
   // ✅ CORRECT
   {"camera_id_eq": 1}
   ```

4. **Is evidence present?**
   ```python
   # Check what evidence is being sent
   print("Evidence:", evidence)
   print("Context:", context)
   ```

5. **Priority conflicts?**
   - Higher priority policies evaluated first
   - If higher priority consumes the event, lower ones may not fire
   - Check for competing policies

### Photo Not Sending

**Symptom:** Policy triggers but no photo in Telegram.

This is a common issue. Here's a complete debugging workflow:

#### Quick Checklist

1. **Both flags set?**
   ```json
   {
     "type": "telegram",
     "send_photo": true,              // ✅ Must be true
     "photo_path": "{latest_frame_path}"  // ✅ Must be set with variable
   }
   ```

2. **Photo file exists?**
   ```powershell
   Test-Path "data/edge_images/test_frame.jpg"  # Should return True
   ```

3. **Evidence includes latest_frame_path?**
   ```python
   evidence = [
       # ... other evidence ...
       {
           'source': 'vision',
           'feature': 'latest_frame_path',        # ✅ Must be present
           'value': 'data/edge_images/test.jpg',  # ✅ Valid file path
           'conf': 1.0
       }
   ]
   ```

#### Deep Debugging

**Step 1: Verify File Exists**
```powershell
# Check if image exists
Test-Path "data/edge_images/test_frame.jpg"

# If false, create a test image
# (Or copy an existing one to this path)
```

**Step 2: Test Direct Photo Sending** (Bypass policy system)
```python
# tests/test_direct_photo.py
from packages.notifiers.telegram import TelegramNotifier
import asyncio

async def test_photo():
    notifier = TelegramNotifier()
    photo_path = "data/edge_images/test_frame.jpg"
    
    print(f"Testing photo send: {photo_path}")
    
    result = await notifier.send_photo(
        photo_path=photo_path,
        caption="🧪 Direct photo test"
    )
    
    print(f"Result: {result}")
    if result:
        print("✅ Photo sent successfully!")
    else:
        print("❌ Photo failed to send")

asyncio.run(test_photo())
```

**Run:**
```powershell
python tests/test_direct_photo.py
```

**Expected Output:**
```
Testing photo send: data/edge_images/test_frame.jpg
[TELEGRAM] Attempting to send photo: data/edge_images/test_frame.jpg
Result: True
✅ Photo sent successfully!
```

**If this fails:** Photo file issue or Telegram API issue, not a policy issue.

**Step 3: Test Policy with Photo** (Standalone evaluation)
```python
# tests/test_policy_with_photo.py
import sqlite3
import asyncio
import time
from packages.policy.apply import evaluate_policies

async def test():
    # Evidence with photo path
    evidence = [
        {'source': 'vision', 'feature': 'vehicle_present', 'value': 'true', 'conf': 0.95},
        {'source': 'vision', 'feature': 'vehicle_color', 'value': 'white', 'conf': 0.85},
        {'source': 'vision', 'feature': 'latest_frame_path', 
         'value': 'data/edge_images/test_frame.jpg', 'conf': 1.0}
    ]
    
    context = {
        'camera_id': 1,
        'track_key': 'test_vehicle',
        'track_type': 'vehicle',
        'event_id': 'test_photo',
        'timestamp': int(time.time())
    }
    
    conn = sqlite3.connect('data/echoBell.db')
    
    try:
        print("Testing policy evaluation with photo...")
        results = await evaluate_policies(evidence, context, conn, use_database=True)
        
        print(f"\nPolicies matched: {len(results)}")
        for r in results:
            print(f"  - {r.get('policy_name')}: {r.get('success')}")
            if 'error' in r:
                print(f"    Error: {r['error']}")
                
    finally:
        conn.close()

asyncio.run(test())
```

**Run:**
```powershell
python tests/test_policy_with_photo.py
```

**Check server logs for:**
```
[POLICY] Matched policy: camera1_vehicle_with_photo
[TELEGRAM] Attempting to send photo: data/edge_images/test_frame.jpg  # ✅ Path substituted
[TELEGRAM] NORMAL: 🚗 Vehicle detected - ✓
```

**If you see `{latest_frame_path}` literally in logs:** Variable not substituting - see below.

#### Common Issues & Fixes

**Issue 1: Variable Not Substituting**

**Symptom:** Logs show `Attempting to send photo: {latest_frame_path}` (literal curly braces)

**Cause:** Variable not in auto-extracted list or evidence missing feature

**Fix:**
```python
# Check packages/policy/evaluator.py around line 499
# Should include 'latest_frame_path' in this list:
if feature in ['color', 'vehicle_type', 'plate_text', 'intent', 'confidence', 
               'visitor_id', 'latest_frame_path', 'vehicle_color', 'person_name']:
    resolved[feature] = str(value)
```

**Issue 2: Relative vs Absolute Paths**

**Symptom:** File exists but "File not found" errors

**Cause:** Working directory mismatch

**Fix:** Use absolute paths or check working directory
```python
import os
photo_path = os.path.abspath("data/edge_images/test.jpg")
```

**Issue 3: File Permissions**

**Symptom:** "Permission denied" errors

**Cause:** Server process can't read file

**Fix:**
```powershell
# Check file permissions (Windows)
Get-Acl "data/edge_images/test.jpg" | Format-List

# Make readable
icacls "data\edge_images\test.jpg" /grant Users:R
```

**Issue 4: Photo Too Large**

**Symptom:** Photo sends but not visible in Telegram

**Cause:** Telegram max photo size is 10MB

**Fix:**
```powershell
# Check file size
(Get-Item "data/edge_images/test.jpg").Length / 1MB  # Should be < 10
```

**Issue 5: Code Not Reloaded**

**Symptom:** Changes to action_handlers.py not taking effect

**Cause:** Server still running old code

**Fix:**
```powershell
# Stop server (CTRL+C in server terminal)
# Then restart:
cd central/policy-server
python server.py
```

### Variables Not Substituting

**Symptom:** Message shows `{vehicle_color}` instead of actual value.

**Check:**

1. **Evidence includes feature?**
   ```python
   # ❌ Missing
   evidence = [
       {'source': 'vision', 'feature': 'vehicle_present', 'value': 'true'}
   ]
   
   # ✅ Included
   evidence = [
       {'source': 'vision', 'feature': 'vehicle_present', 'value': 'true'},
       {'source': 'vision', 'feature': 'vehicle_color', 'value': 'white'}  # ✅
   ]
   ```

2. **Variable name matches feature?**
   ```json
   // Evidence feature: "vehicle_color"
   // Variable: {vehicle_color}  ✅
   // Variable: {color}          ✅ (alternate)
   // Variable: {car_color}      ❌ (won't match)
   ```

3. **Use fallback format:**
   ```
   {source}_{feature}
   
   Example: {vision_vehicle_color}
   ```

### Alert Cooldown Not Working

**Symptom:** Getting spammed with alerts.

**Check:**

1. **alert_history table exists?**
   ```sql
   SELECT name FROM sqlite_master WHERE type='table' AND name='alert_history';
   ```
   If not found, run migration:
   ```bash
   python -c "import sqlite3; conn = sqlite3.connect('data/echoBell.db'); \
              conn.executescript(open('infra/db/migrations/010_add_alert_history.sql').read()); \
              conn.commit()"
   ```

2. **Correct condition syntax?**
   ```json
   {
     "no_recent_alert": {
       "track_type": "vehicle",      // Must match evidence track_type
       "within_seconds": 300          // Cooldown period
     }
   }
   ```

3. **Track keys consistent?**
   - Cooldown checks by `track_key`
   - If track_key changes each time, cooldown won't work
   - Ensure track_key is stable for same object

### Database Issues

**Symptom:** Can't find database or policies.

**Check:**

1. **Correct database file?**
   ```bash
   # Server uses echoBell.db (check server.py)
   ls -la data/echoBell.db
   
   # NOT doorbell.db
   ```

2. **Policy in correct database?**
   ```bash
   # List policies
   sqlite3 data/echoBell.db "SELECT id, name FROM policy_rules"
   ```

3. **Schema up to date?**
   ```bash
   # Check for policy_rules table
   sqlite3 data/echoBell.db ".schema policy_rules"
   ```

---

## Best Practices

### 1. Start Simple
Begin with minimal conditions and add complexity gradually.

### 2. Use Descriptive Names
```json
// ❌ Bad
{"id": "pol1", "name": "Policy 1"}

// ✅ Good  
{"id": "cam1_vehicle_photo", "name": "Camera 1 - Vehicle Detection with Photo"}
```

### 3. Add Cooldowns
Prevent alert spam:
```json
{
  "conditions": {
    "all": [
      // ... your conditions ...
      {"no_recent_alert": {"track_type": "vehicle", "within_seconds": 300}}
    ]
  }
}
```

### 4. Test Before Production
Always test with sample evidence before deploying.

### 5. Document Your Policies
Use the `description` field:
```json
{
  "description": "Alerts when white vehicles detected on camera 1 during business hours"
}
```

### 6. Version Your Policies
Use tags and version numbers:
```json
{
  "tags": "vehicle camera1 production",
  "version": 2
}
```

### 7. Monitor Performance
- High priority = 80+
- Normal = 50-79
- Background = 20-49
- Fallback = 1-19

---

## Quick Reference

### Condition Types Cheat Sheet

```
Camera:      camera_id_eq, camera_id_in
Evidence:    evidence_exists, evidence_missing, evidence_value_eq/gt/lt
Time:        track_duration_gt/lt, time_between, day_of_week
Alerts:      no_recent_alert, alert_sent_within
Trust:       trust_check
Event:       event_type
Logic:       all, any, none
```

### Action Types Cheat Sheet

```
telegram     - Send message (+ optional photo)
speak        - Text-to-speech
webhook      - HTTP POST
create_watch - Deferred evaluation
```

### Common Variables

```
{camera_id}          - Camera identifier
{track_key}          - Track identifier
{vehicle_color}      - Vehicle color from vision
{vehicle_type}       - Vehicle type from vision
{plate_text}         - License plate text
{person_name}        - Person name (if identified)
{latest_frame_path}  - Path to captured frame
```

---

## Getting Help

1. **Check Logs:**
   ```bash
   tail -f data/logs/policy_api.json
   ```

2. **Test Evidence:**
   Use `test_policy_with_photo.py` to validate evidence/context

3. **Inspect Database:**
   ```bash
   sqlite3 data/echoBell.db "SELECT * FROM policy_rules WHERE id = 'my_policy'"
   ```

4. **Enable Debug Logging:**
   Check evaluator logs for condition matching details
