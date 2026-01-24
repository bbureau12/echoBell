# Trust System & Policy Decision Flow

## Overview

EchoBell's trust system enables intelligent policy decisions by identifying known vehicles and people. This document explains how trust flows through the system from edge detection to policy actions.

## Trust Registries

### 1. Trusted Plates (`trusted_plates`)
- **Purpose**: Identify known vehicles (family cars, delivery vans, neighbors)
- **Storage**: Privacy-safe HMAC of plate text + human-readable label
- **Location**: `packages/perception/plate_service.py`

```sql
CREATE TABLE trusted_plates (
    plate_hmac TEXT PRIMARY KEY,      -- HMAC("ABC1234")
    label TEXT NOT NULL,              -- "Wife's Car", "Amazon Delivery"
    enabled INTEGER DEFAULT 1
);
```

### 2. Trusted People (`trusted_person` + `trusted_person_embedding`)
- **Purpose**: Identify known individuals via facial recognition
- **Storage**: Face embeddings + person metadata
- **Location**: Migration 006

```sql
CREATE TABLE trusted_person (
    trusted_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,        -- "John Doe"
    label TEXT,                       -- "family", "neighbor"
    active INTEGER DEFAULT 1
);
```

### 3. Alert History (`alert_history`)
- **Purpose**: Prevent alert spam and enable escalation logic
- **Storage**: Track when alerts were sent for each entity
- **Location**: Migration 010

```sql
CREATE TABLE alert_history (
    camera_id TEXT,
    track_key TEXT,                   -- plate_hmac or visitor_id
    alert_type TEXT,                  -- 'telegram', 'speak'
    priority TEXT,                    -- 'normal', 'urgent'
    sent_ts INTEGER
);
```

## Trust Flow: Edge to Policy

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. EDGE CAPTURE (doorbell-agent/orchestrator.py)               │
└─────────────────────────────────────────────────────────────────┘
    │
    ├─> Camera captures frame
    ├─> Vision detection: Vehicle + Person
    ├─> OCR extracts plate: "ABC1234"
    ├─> Face recognition extracts embedding
    │
    └─> Send to Policy API: POST /evidence
        {
          "camera_id": "front_door",
          "objects": [
            {"type": "vehicle", "bbox": [...], "plate_text": "ABC1234"},
            {"type": "person", "bbox": [...], "face_embedding": [...]}
          ]
        }

┌─────────────────────────────────────────────────────────────────┐
│ 2. TRUST CHECK (Policy API /evidence endpoint)                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ├─> VEHICLE TRUST CHECK
    │   ├─> plate_hmac = HMAC("ABC1234")
    │   ├─> Query: SELECT label FROM trusted_plates WHERE plate_hmac = ?
    │   │   └─> Found: label = "Wife's Car"
    │   └─> Add evidence: Evidence("plate_trust", "trusted_plate", "Wife's Car", 1.0)
    │
    ├─> PERSON TRUST CHECK
    │   ├─> Compare face_embedding vs trusted_person_embedding table
    │   ├─> Similarity > 0.8 → Match: trusted_id=5, name="John Doe"
    │   └─> Add evidence: Evidence("face", "visitor_id", "vis_john_doe", 0.92)
    │
    └─> MOVEMENT ANALYSIS
        ├─> Compare current bbox with scene_tracks.last_box_json
        ├─> Distance > 50px → Evidence("movement", "position_changed", "141.4px", 1.0)
        └─> Missing from scene → Evidence("movement", "vehicle_exited", "", 1.0)

┌─────────────────────────────────────────────────────────────────┐
│ 3. POLICY EVALUATION (Future: /policy/evaluate endpoint)       │
└─────────────────────────────────────────────────────────────────┘
    │
    ├─> Gather all evidence for track_key
    │   ├─> Trust evidence: "Wife's Car" (plate_trust.trusted_plate)
    │   ├─> Movement evidence: "position_changed" (movement.position_changed)
    │   └─> Scene evidence: "vehicle_entered" (scene.vehicle_entered)
    │
    ├─> Evaluate policy rules (config/policies.yaml)
    │   │
    │   ├─> Rule: "trusted_vehicle_arrival"
    │   │   Conditions:
    │   │     - plate_trust.trusted_plate EXISTS
    │   │     - scene.vehicle_entered = "1"
    │   │   Actions:
    │   │     - telegram: "Wife's Car arrived home"
    │   │     - speak: None (silent entry for family)
    │   │
    │   ├─> Rule: "unknown_vehicle_alert"
    │   │   Conditions:
    │   │     - plate_trust.trusted_plate NOT EXISTS
    │   │     - scene.vehicle_entered = "1"
    │   │   Actions:
    │   │     - telegram: "⚠️ Unknown vehicle pulled up"
    │   │     - speak: "Hello, how can I help you?"
    │   │
    │   └─> Rule: "loitering_escalation"
    │       Conditions:
    │         - movement.loitering EXISTS
    │         - plate_trust.trusted_plate NOT EXISTS
    │         - alert_history: sent_ts < (now - 300s)  # 5 min ago
    │       Actions:
    │         - telegram: "⚠️ URGENT: Person still loitering after 5 min"
    │         - speak: "This is private property. Please leave."
    │
    └─> Check alert_history (spam prevention)
        ├─> Query: SELECT sent_ts FROM alert_history 
        │          WHERE track_key = ? AND sent_ts > (now - 300)
        ├─> If recent alert found: Skip or escalate priority
        └─> If no recent alert: Send new alert

┌─────────────────────────────────────────────────────────────────┐
│ 4. ACTION EXECUTION (Notifiers + TTS)                          │
└─────────────────────────────────────────────────────────────────┘
    │
    ├─> TELEGRAM NOTIFICATION
    │   └─> Send message: "Wife's Car arrived home"
    │
    ├─> TTS ANNOUNCEMENT (optional)
    │   └─> Piper TTS: "Hello, how can I help you?"
    │
    └─> RECORD ALERT
        └─> INSERT INTO alert_history (track_key, alert_type, sent_ts)
            VALUES ("plate_abc123", "telegram", 1737750000)
```

## Example Policy Scenarios

### Scenario 1: Unknown Car Arrival
```
Evidence:
  - vision.vehicle_present = "true"
  - vision.vehicle_type = "car"
  - vision.color = "black"
  - ocr.plate_text = "XYZ9999"
  - plate_trust.trusted_plate = NOT FOUND
  - scene.vehicle_entered = "1"

Policy Match: "unknown_vehicle_alert"

Actions:
  ✅ Telegram: "⚠️ Unknown black car (XYZ9999) pulled up at Front Door"
  ✅ Speak: "Hello! How can I help you today?"
  ✅ Record: alert_history (track_key="plate_xyz9999", type="telegram")
```

### Scenario 2: Trusted Person Arrives
```
Evidence:
  - vision.person_present = "true"
  - face.visitor_id = "vis_john_doe"
  - trusted_person: name="John Doe", label="family"
  - scene.person_entered = "1"
  - movement.position_changed = "85.3px"

Policy Match: "trusted_person_arrival"

Actions:
  ✅ Telegram: "John Doe arrived home"
  ❌ Speak: None (silent entry for family)
  ✅ Record: alert_history (track_key="vis_john_doe", type="telegram")
```

### Scenario 3: Delivery Van Recognition
```
Evidence:
  - vision.vehicle_present = "true"
  - vision.vehicle_type = "truck"
  - ocr.plate_text = "AMZ5678"
  - plate_trust.trusted_plate = "Amazon Delivery"
  - scene.vehicle_entered = "1"

Policy Match: "delivery_instruction"

Actions:
  ✅ Telegram: "Amazon delivery at Front Door"
  ✅ Speak: "Thanks for the delivery! Please leave it by the door."
  ✅ Record: alert_history (track_key="plate_amz5678", type="speak")
```

### Scenario 4: Loitering Escalation
```
T=0s:
Evidence:
  - vision.person_present = "true"
  - plate_trust.trusted_plate = NOT FOUND
  - scene.person_entered = "1"

Policy Match: "unknown_person_initial"
Actions:
  ✅ Telegram: "Unknown person detected at Front Door"
  ✅ Record: alert_history (sent_ts=T0)

T=300s (5 minutes later):
Evidence:
  - movement.loitering = "300s" (still present, <20px movement)
  - alert_history: last_alert_ts = T0 (5 min ago)

Policy Match: "loitering_escalation"
Actions:
  ✅ Telegram: "⚠️ URGENT: Person still loitering after 5 minutes"
  ✅ Speak: "This is private property. Please leave or I will call authorities."
  ✅ Record: alert_history (sent_ts=T300, priority="urgent")
```

## Alert Spam Prevention

```python
def should_send_alert(track_key, alert_type, cooldown_seconds=300):
    """Check if we should send alert or skip due to recent alert."""
    
    # Query alert history
    recent = db.execute("""
        SELECT sent_ts, priority FROM alert_history
        WHERE track_key = ? AND alert_type = ?
        AND sent_ts > ?
        ORDER BY sent_ts DESC LIMIT 1
    """, (track_key, alert_type, now_ts - cooldown_seconds)).fetchone()
    
    if not recent:
        return True  # No recent alert, send it
    
    # Check if we should escalate
    time_since_alert = now_ts - recent[0]
    if time_since_alert >= 300 and recent[1] != "urgent":
        return True  # Escalate after 5 minutes
    
    return False  # Skip, too recent
```

## Managing Trust Registries

### Adding Trusted Plate
```python
from packages.perception.plate_service import PlateService

plate_service = PlateService(secret_key=b"your_secret_key")

# Add trusted plate
plate_service.add_trusted_plate(
    conn,
    raw_plate_text="ABC1234",
    label="Wife's Car",
    enabled=True,
    notes="2019 Honda Accord, white"
)
```

### Adding Trusted Person
```sql
-- Add person
INSERT INTO trusted_person (name, label, created_ts, active)
VALUES ('John Doe', 'family', 1737750000, 1);

-- Add face embedding
INSERT INTO trusted_person_embedding 
(trusted_id, embedding_type, model_name, embedding_dim, embedding_blob, created_ts)
VALUES (1, 'face', 'insightface', 512, <blob_data>, 1737750000);
```

### Checking Trust Status
```python
# Check plate trust
trust_info = plate_service.is_plate_trusted(conn, "ABC1234")
# Returns: {"plate_hmac": "a3f2...", "label": "Wife's Car", "enabled": True}

# Check person trust
embedding = face_model.get_embedding(face_crop)
matches = find_similar_embeddings(embedding, threshold=0.8)
# Returns: [{"trusted_id": 5, "name": "John Doe", "similarity": 0.92}]
```

## Privacy Guarantees

1. **Plate Privacy**: Raw plate text never stored
   - Only HMAC stored: `HMAC-SHA256("ABC1234" + secret_salt)`
   - Reversibility: Impossible without secret key
   
2. **Face Privacy**: Raw images never stored
   - Only embedding vectors stored (512-dim float array)
   - Original face cannot be reconstructed from embedding
   
3. **Trust Labels**: Human-readable for operators
   - "Wife's Car" instead of cryptic IDs
   - Easy to audit and manage

## Future Enhancements

1. **Temporal Trust Patterns**
   - "Delivery van expected Mon-Fri 2-4pm"
   - "Neighbor visiting Sat mornings"
   
2. **Cross-Camera Trust**
   - "John Doe active on camera 1 and 2" (moving through property)
   - Suppress duplicate alerts when person moves between cameras
   
3. **Trust Levels**
   - `family` (full trust, silent entry)
   - `trusted_neighbor` (notification only)
   - `delivery` (auto-instruction, no alert)
   - `guest` (temporary trust, expires after date)
   - `banned` (immediate urgent alert)

4. **Behavioral Trust Scoring**
   - Learn from past visits
   - "Plate XYZ seen 50x, always delivery intent" → auto-trust

---

**Last Updated**: January 24, 2026  
**Related**: ARCHITECTURE.md, config/policies.yaml, Migration 010
