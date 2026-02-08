# EchoBell Two-Layer Architecture

**Document Version**: 1.0  
**Last Updated**: February 8, 2026  
**Status**: Active

---

## Overview

EchoBell uses a **two-layer architecture** that separates perception from decision-making:

1. **Edge Device Layer** - Observes the physical world (sensing)
2. **Policy/Decision Layer** - Analyzes observations and makes decisions (intelligence)

This separation enables:
- **Scalability**: Multiple edge devices → single policy server
- **Centralized intelligence**: Complex logic runs once, not on every device
- **Privacy**: Raw images stay on edge, only metadata sent to central
- **Flexibility**: Upgrade policies without touching edge devices
- **Resilience**: Edge devices can operate in degraded mode if policy server is down

---

## Layer 1: Edge Device Layer (Perception)

### Purpose
Capture and process sensory data from the physical environment.

### Location
- `edge/agent/` - Main agent code
- `packages/perception/` - Vision, OCR, face recognition

### Core Responsibilities

#### 1. **Image Capture & Detection**
- Continuous camera monitoring (`camera_loop.py`)
- Button-triggered capture (`button_loop.py`)
- YOLO object detection (people, vehicles, packages, dogs)
- Bounding box and confidence scores

#### 2. **Visual Analysis**
- **OCR**: License plate text extraction (PaddleOCR)
- **Face Recognition**: Embedding extraction (InsightFace)
- **Color Analysis**: Vehicle/clothing color detection
- **Age Estimation**: Approximate age from faces

#### 3. **Audio Processing** (doorbell mode)
- Button press detection
- ASR transcription (speech-to-text)
- TTS playback (text-to-speech)

#### 4. **Evidence Collection**
Structured observations sent to policy layer:
```python
Evidence(
    source="vision",      # or "ocr", "asr", "button"
    feature="person_present",
    value="true",
    conf=0.95,
    object_id=1
)
```

#### 5. **Image Serving**
- Local HTTP server for on-demand image access
- Retention policies (auto-cleanup)
- Privacy: images never leave local network unless explicitly sent

### What Edge Layer Does NOT Do
- ❌ Trust evaluation (doesn't know which plates/faces are trusted)
- ❌ Scene tracking (doesn't track persistence across time)
- ❌ Policy decisions (doesn't decide what actions to take)
- ❌ Historical analysis (no long-term memory)
- ❌ Intent classification (doesn't infer visitor intent)

### Key Files
```
edge/agent/
├── main.py              # Unified edge agent entry point
├── camera_loop.py       # Passive camera monitoring
├── button_loop.py       # Doorbell button handling
├── image_server.py      # HTTP server for images
└── config.yaml          # Edge device configuration

packages/perception/
├── vision.py            # YOLO + OCR + face recognition
├── ocr.py               # License plate OCR
├── visitor.py           # Face recognition
├── age.py               # Age estimation
└── plate_heurystics.py  # Plate validation logic
```

---

## Layer 2: Policy/Decision Layer (Central Intelligence)

### Purpose
Analyze observations from multiple edge devices, track state over time, and make intelligent decisions.

### Location
- `central/policy-server/` - FastAPI server
- `packages/policy/` - Policy engine
- `packages/scene/` - Scene tracking
- `packages/presence/` - Presence tracking

### Core Responsibilities

#### 1. **Scene Tracking**
- Track objects across multiple frames
- Detect arrivals, departures, loitering
- Person-vehicle linkage
- Multi-camera correlation

#### 2. **Trust Evaluation**
- Check if plates/faces are in trusted lists
- Historical visit patterns
- Reputation scoring
- Trust inheritance (person → vehicle)

#### 3. **Policy Rule Evaluation**
Policy rules match evidence patterns:
```yaml
- id: quiet_hours_visitor
  conditions:
    all:
      - evidence_exists: {source: "vision", feature: "person_present"}
      - time_range: {start: "22:00", end: "07:00"}
  actions:
    - type: telegram
      message: "Visitor during quiet hours"
```

#### 4. **Intent Classification**
Infer visitor purpose from multimodal evidence:
- Text patterns (uniform keywords)
- Visual signals (packages, vehicles)
- Historical patterns (repeat visitor)
- Trust signals (known face/plate)
- Scene context (how long present, linked to vehicle)

#### 5. **Action Execution**
- **Telegram**: Send photos and alerts
- **TTS**: Request edge device to speak
- **Webhooks**: Trigger external systems
- **Logging**: Store evidence for future analysis

#### 6. **LLM Integration**
- Natural language understanding
- Conversational responses
- Scene queries
- Dynamic listening mode control

#### 7. **Presence Management**
- Track who is home
- Phone heartbeats, vehicle arrivals, face detection
- Multi-source confidence aggregation

### What Policy Layer Does NOT Do
- ❌ Image capture (relies on edge devices)
- ❌ Real-time object detection (uses edge results)
- ❌ Physical actuation (requests edge to execute)

### Key Files
```
central/policy-server/
├── server.py            # FastAPI endpoints
├── services.py          # Business logic
├── api_voice.py         # Voice command API
└── api_policies.py      # Policy management API

packages/policy/
├── evaluator.py         # Rule engine
├── executor.py          # Action execution
├── action_handlers.py   # Telegram, TTS, webhooks
└── policy_service.py    # CRUD for policies

packages/scene/
├── scene_tracker.py     # Object persistence tracking
└── movement_analyzer.py # Movement pattern detection

packages/presence/
└── presence_service.py  # Home/away tracking
```

---

## Communication Protocol

### Edge → Policy: Observations

**Endpoint**: `POST /evidence`

**Payload**:
```json
{
  "camera_id": 1,
  "event_id": "evt_1737585600_1",
  "timestamp": 1737585600,
  "objects": [
    {
      "object_id": 1,
      "label": "person",
      "bbox": [100, 200, 180, 350],
      "confidence": 0.95,
      "props": {"color": "tan"}
    }
  ],
  "evidence": [
    {
      "source": "vision",
      "feature": "person_present",
      "value": "true",
      "conf": 0.95
    },
    {
      "source": "ocr",
      "feature": "plate_text",
      "value": "ABC1234",
      "conf": 0.88
    }
  ],
  "transcript": "Hello, I have a delivery",
  "context": {
    "mode": "doorbell",
    "person_present": true,
    "vehicle_present": true
  }
}
```

### Policy → Edge: Actions

**Response**:
```json
{
  "received": true,
  "event_id": "evt_1737585600_1",
  "actions": [
    {
      "type": "speak",
      "message": "Please leave the package at the door"
    }
  ],
  "message": "Logged 5 evidence items, executed 2 policy actions"
}
```

### Action Types

| Type | Executed By | Description |
|------|-------------|-------------|
| `telegram` | Policy Server | Send photo/message via Telegram |
| `speak` | Edge Device | TTS playback on doorbell speaker |
| `webhook` | Policy Server | POST to external URL |
| `log` | Both | Console/database logging |

---

## Data Flow: Complete Example

### Scenario: Sheriff Arrives at Door

```
┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: EDGE DEVICE                                        │
└─────────────────────────────────────────────────────────────┘

1. Camera detects vehicle + person
   └─> YOLO: person (conf=0.95), vehicle (conf=0.92)

2. OCR extracts plate
   └─> PaddleOCR: "SHERIFF1" (conf=0.88)

3. Color analysis
   └─> Vehicle: black (conf=0.85)
   └─> Person: tan clothing (conf=0.80)

4. Button pressed, ASR activated
   └─> Transcript: "I'm here to check on a noise complaint"

5. Package observations as Evidence
   └─> Build JSON payload with objects + evidence + transcript

6. POST to Policy Server
   └─> http://policy-server:8000/evidence

┌─────────────────────────────────────────────────────────────┐
│ LAYER 2: POLICY SERVER                                      │
└─────────────────────────────────────────────────────────────┘

7. Receive observations from edge

8. Scene Tracking
   └─> Check if vehicle seen before (scene_tracks table)
   └─> Generate scene.vehicle_entered evidence
   └─> Link person to vehicle (co-occurrence)

9. Trust Evaluation
   └─> Check plate_text against trusted_plates
   └─> Match: plate="SHERIFF1", label="sheriff"
   └─> Add Evidence("plate_trust", "trusted_plate", "sheriff", 1.0)

10. Intent Classification
    └─> Text pattern: "sheriff" keyword found
    └─> Visual: tan uniform detected
    └─> Trust: plate_trust.trusted_plate="sheriff"
    └─> Combined confidence: 0.95
    └─> INTENT: sheriff

11. Policy Evaluation
    └─> Match rule: sheriff_visitor
    └─> Conditions: all([
          evidence_exists("sheriff"),
          trust_level("high")
        ])
    └─> Actions: [
          {"type": "telegram", "message": "Sheriff at door"},
          {"type": "speak", "message": "Hello officer"}
        ]

12. Execute Actions
    └─> Send Telegram (policy server)
        └─> Download image from edge HTTP server
        └─> Send to Telegram with caption
    └─> Queue TTS (return to edge)

13. Return response to edge device
    └─> JSON with actions: [{"type": "speak", ...}]

┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: EDGE DEVICE (Response)                             │
└─────────────────────────────────────────────────────────────┘

14. Edge receives policy response

15. Execute local actions
    └─> TTS: "Hello officer"
    └─> Speaker plays audio

16. Continue monitoring
```

---

## Deployment Topologies

### Single Device (Development)

```
┌─────────────────────────────────┐
│  Laptop / Dev Machine           │
│                                 │
│  ┌───────────────────────────┐ │
│  │ Edge Agent (localhost)    │ │
│  │ Port: 8080 (images)       │ │
│  └──────────┬────────────────┘ │
│             │                   │
│  ┌──────────▼────────────────┐ │
│  │ Policy Server             │ │
│  │ Port: 8000 (API)          │ │
│  └───────────────────────────┘ │
│                                 │
│  Database: data/doorbell.db    │
└─────────────────────────────────┘
```

### Multi-Camera LAN

```
┌──────────────────────┐      ┌──────────────────────┐
│ Edge Device 1        │      │ Edge Device 2        │
│ (Front Door)         │      │ (Driveway)           │
│                      │      │                      │
│ Camera + Doorbell    │      │ Camera (passive)     │
│ Port: 8081           │      │ Port: 8082           │
└──────────┬───────────┘      └──────────┬───────────┘
           │                             │
           │         ┌───────────────────┘
           │         │
           └─────────┼─────────┐
                     ▼         │
          ┌──────────────────────────┐
          │  Policy Server           │
          │  (Central)               │
          │                          │
          │  - Scene tracking        │
          │  - Trust evaluation      │
          │  - Policy decisions      │
          │  - Telegram integration  │
          │                          │
          │  Port: 8000              │
          └──────────────────────────┘
```

### Remote Deployment

```
┌──────────────────────┐
│ Edge Device          │
│ (Home Network)       │
│ 192.168.1.100:8080   │
└──────────┬───────────┘
           │
           │ Internet (tunneled/VPN)
           │
           ▼
┌──────────────────────┐
│ Policy Server        │
│ (Cloud / VPS)        │
│                      │
│ https://api.echo.io  │
└──────────────────────┘
```

---

## Design Rationale

### Why Two Layers?

#### **Performance**
- Heavy ML models (YOLO, OCR) run once on edge
- Policy server focuses on logic, not pixel processing
- Edge devices can be low-power (Raspberry Pi)

#### **Privacy**
- Raw images never leave edge device
- Only metadata and embeddings sent to central
- Images served on-demand via private HTTP

#### **Scalability**
- One policy server handles 10+ edge devices
- Centralized scene tracking across cameras
- Shared trust database and visitor history

#### **Maintainability**
- Update policies without touching edge code
- Edge devices are "dumb sensors" (simple)
- Complex logic isolated in policy layer

#### **Resilience**
- Edge can operate in fallback mode if policy down
- Local image retention prevents data loss
- Eventual consistency when connection restored

### What Stays Local vs Central?

| Capability | Edge | Policy | Reason |
|------------|------|--------|--------|
| Object Detection | ✅ | ❌ | Needs camera access, heavy compute |
| Face Recognition | ✅ | ❌ | Privacy: embeddings only sent |
| Scene Tracking | ❌ | ✅ | Needs state across cameras/time |
| Trust Evaluation | ❌ | ✅ | Centralized trust database |
| Policy Rules | ❌ | ✅ | Complex logic, frequent updates |
| Image Storage | ✅ | ❌ | Too bandwidth-heavy to upload all |
| Telegram Sending | ❌ | ✅ | Needs bot credentials, internet |
| TTS Playback | ✅ | ❌ | Needs speaker hardware |
| ASR Capture | ✅ | ❌ | Needs microphone hardware |

---

## Configuration

### Edge Device (`edge/agent/config.yaml`)

```yaml
agent:
  camera_id: 1              # Unique device ID
  mode: doorbell            # "doorbell" or "guard"
  has_button: true
  has_speaker: true
  has_microphone: true

camera:
  rtsp_url: rtsp://camera/stream
  poll_sec: 1.0
  persistence_threshold: 3.0

policy_api:
  base_url: http://policy-server:8000
  timeout: 5
  max_retries: 3

image_server:
  enabled: true
  port: 8080
  directory: /tmp/echoBell/images

fallback:
  warn_only: true           # Continue if policy server down
```

### Policy Server (`central/policy-server/.env`)

```bash
ECHOBELL_DB_PATH=/data/echoBell.db
POLICY_API_HOST=0.0.0.0
POLICY_API_PORT=8000

# Telegram (for action execution)
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Scene tracking config
SCENE_IOU_THRESHOLD=0.3
SCENE_GRACE_PERIOD_S=6
```

---

## Testing Strategy

### Unit Tests
- **Edge**: Test vision detection, OCR, face recognition
- **Policy**: Test rule evaluation, action execution, scene tracking

### Integration Tests
- **API**: Test edge → policy communication (`tests/api/`)
- **E2E**: Full flow from camera → detection → policy → action

### Example: Integration Test

```python
def test_sheriff_detection_flow(api_client):
    """Test complete flow: edge detects sheriff, policy responds."""
    client, conn = api_client
    
    # 1. Edge sends observations
    payload = {
        "camera_id": 1,
        "objects": [{"label": "person", ...}],
        "evidence": [
            {"source": "ocr", "feature": "plate_text", "value": "SHERIFF1"},
            {"source": "vision", "feature": "uniform_color", "value": "tan"}
        ]
    }
    
    # 2. Policy server processes
    response = client.post("/evidence", json=payload)
    assert response.status_code == 200
    
    # 3. Check policy matched and actions returned
    data = response.json()
    assert any(a['type'] == 'telegram' for a in data['actions'])
```

---

## Troubleshooting

### Edge Device Can't Reach Policy Server

**Symptoms**: `[POLICY_API] WARNING: Failed to contact policy server`

**Checks**:
1. Verify network connectivity: `ping policy-server`
2. Check policy server is running: `curl http://policy-server:8000/health`
3. Review `fallback.warn_only` config (edge continues if `true`)
4. Check firewall rules on policy server

### Images Not Accessible for Telegram

**Symptoms**: Telegram sends text but no photo

**Checks**:
1. Verify image server running: `curl http://edge-device:8080/images/test.jpg`
2. Check `snapshot_url` in policy server logs
3. Ensure policy server can reach edge network
4. Review retention settings (images auto-deleted?)

### Scene Tracking Not Working

**Symptoms**: No `scene.vehicle_entered` evidence

**Checks**:
1. Verify objects have `object_id` (required for tracking)
2. Check IoU threshold in policy server config
3. Review `scene_tracks` table in database
4. Enable debug logging: `logging.level: DEBUG`

---

## Migration Notes

### From Monolithic to Two-Layer

If you're upgrading from an older monolithic design:

1. **Split classify_and_log**: 
   - Keep vision detection on edge
   - Move scene tracking to policy server
   
2. **Update Tests**:
   - Tests using local `SceneTracker` → use API client
   - See `docs/archive/TEST_MIGRATION_GUIDE.md`
   
3. **Database**:
   - Edge devices can share read-only DB (for vision_class_map)
   - Policy server owns read-write (for policies, scene_tracks)

---

## Future Enhancements

### Planned
- [ ] Edge-side caching of trust lists (reduce API calls)
- [ ] Offline mode: edge stores observations, syncs when online
- [ ] Multi-policy-server for HA/load balancing
- [ ] gRPC instead of REST for lower latency
- [ ] Federated learning: edge trains local models, shares gradients

### Under Consideration
- [ ] Edge-side intent classification (low-confidence only)
- [ ] Policy server pushes config updates to edge (websocket)
- [ ] Blockchain for immutable evidence audit trail

---

## Related Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Full system architecture
- **[edge/agent/README.md](../edge/agent/README.md)** - Edge device setup
- **[TRUST_FLOW.md](TRUST_FLOW.md)** - Trust evaluation flow
- **[guides/EDGE_DEVICES_GUIDE.md](guides/EDGE_DEVICES_GUIDE.md)** - Image serving options
- **[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)** - Database tables and relationships

---

## Quick Reference

### Edge Device Capabilities
✅ Image capture  
✅ Object detection (YOLO)  
✅ OCR (plates)  
✅ Face recognition  
✅ Color analysis  
✅ ASR/TTS (doorbell mode)  
✅ Local image serving  
❌ Scene tracking  
❌ Trust evaluation  
❌ Policy decisions  
❌ Historical analysis  

### Policy Server Capabilities
✅ Scene tracking (multi-camera)  
✅ Trust evaluation  
✅ Policy rule engine  
✅ Intent classification  
✅ Action execution (Telegram, webhooks)  
✅ LLM integration  
✅ Presence tracking  
✅ Historical analysis  
❌ Image capture  
❌ Real-time object detection  

### Communication
- **Protocol**: HTTP/REST
- **Direction**: Edge → Policy (observations), Policy → Edge (actions)
- **Format**: JSON
- **Frequency**: Event-driven (detections, button presses)
- **Fallback**: Edge continues in degraded mode if policy unreachable
