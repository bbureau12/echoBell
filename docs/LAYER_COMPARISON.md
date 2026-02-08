# Layer Comparison Chart

Quick reference for understanding what capabilities belong to each layer.

## At a Glance

```
┌─────────────────────────────────────────────────────────────┐
│                    EDGE DEVICE LAYER                        │
│                   (Sensing & Capture)                       │
├─────────────────────────────────────────────────────────────┤
│ • Camera/microphone access                                  │
│ • YOLO object detection                                     │
│ • OCR (license plates)                                      │
│ • Face recognition (embeddings)                             │
│ • Color analysis                                            │
│ • ASR/TTS (audio in/out)                                   │
│ • Local image storage & HTTP serving                        │
│ • Evidence packaging (structured observations)              │
└─────────────────────────────────────────────────────────────┘
                             │
                             │ HTTP POST /evidence
                             │ (objects, evidence, transcript)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   POLICY/DECISION LAYER                     │
│                  (Intelligence & Actions)                   │
├─────────────────────────────────────────────────────────────┤
│ • Scene tracking (multi-camera, temporal)                   │
│ • Trust evaluation (known plates/faces)                     │
│ • Policy rule engine                                        │
│ • Intent classification                                     │
│ • Historical analysis                                       │
│ • LLM integration                                           │
│ • Action execution (Telegram, webhooks)                     │
│ • Presence tracking                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Detailed Comparison

| Capability | Edge Layer | Policy Layer | Reason |
|------------|------------|--------------|--------|
| **Hardware Access** | | | |
| Camera/Video | ✅ | ❌ | Physical connection to camera |
| Microphone | ✅ | ❌ | Physical connection to mic |
| Speaker | ✅ | ❌ | Physical connection to speaker |
| Button/GPIO | ✅ | ❌ | Local hardware interface |
| **ML & Vision** | | | |
| Object Detection (YOLO) | ✅ | ❌ | Needs camera feed, heavy compute |
| OCR (plates) | ✅ | ❌ | Needs image crops |
| Face Recognition | ✅ | ❌ | Privacy: only embeddings sent |
| Color Analysis | ✅ | ❌ | Needs pixel data |
| Age Estimation | ✅ | ❌ | Needs face crops |
| **Audio Processing** | | | |
| ASR (speech-to-text) | ✅ | ❌ | Needs microphone access |
| TTS (text-to-speech) | ✅ | ❌ | Needs speaker hardware |
| LLM Processing | ❌ | ✅ | CPU-intensive, shared across devices |
| **State & Memory** | | | |
| Scene Tracking | ❌ | ✅ | Needs state across cameras/time |
| Trust Evaluation | ❌ | ✅ | Centralized trust database |
| Visitor History | ❌ | ✅ | Long-term memory |
| Presence Tracking | ❌ | ✅ | Multi-source aggregation |
| **Logic & Decisions** | | | |
| Policy Rule Engine | ❌ | ✅ | Complex logic, frequent updates |
| Intent Classification | ❌ | ✅ | Historical context needed |
| Action Selection | ❌ | ✅ | Policy-driven decisions |
| **Data & Storage** | | | |
| Image Storage (raw) | ✅ | ❌ | Privacy: stays local |
| Image Serving (HTTP) | ✅ | ❌ | On-demand access from policy |
| Evidence Logging | ❌ | ✅ | Centralized audit trail |
| Event Database | ❌ | ✅ | Shared across all devices |
| **External Integration** | | | |
| Telegram Bot | ❌ | ✅ | Needs bot credentials, internet |
| Webhooks | ❌ | ✅ | Centralized HTTP client |
| Email | ❌ | ✅ | Centralized SMTP |
| **Data Sent** | | | |
| Objects & Bounding Boxes | ✅ → | ← | Edge sends to policy |
| Evidence (structured) | ✅ → | ← | Edge sends to policy |
| Transcripts | ✅ → | ← | Edge sends to policy |
| Face Embeddings | ✅ → | ← | Edge sends to policy (not raw images) |
| Plate HMACs | ✅ → | ← | Edge sends to policy (not raw text) |
| **Data Received** | | | |
| Actions to Execute | ← | ✅ → | Policy tells edge what to do |
| TTS Messages | ← | ✅ → | Policy tells edge what to say |
| Config Updates | ← | ✅ → | Future: policy pushes config |

---

## Data Flow Summary

### Edge → Policy (Observations)
```json
{
  "camera_id": 1,
  "objects": [{
    "object_id": 1,
    "label": "person",
    "bbox": [100, 200, 180, 350],
    "confidence": 0.95
  }],
  "evidence": [{
    "source": "vision",
    "feature": "person_present",
    "value": "true",
    "conf": 0.95
  }],
  "transcript": "Hello, I have a delivery"
}
```

### Policy → Edge (Actions)
```json
{
  "actions": [{
    "type": "speak",
    "message": "Please leave the package at the door"
  }]
}
```

---

## Why This Separation?

### Performance
- **Heavy ML** (YOLO, OCR) runs once on edge, close to camera
- **Policy logic** runs centrally, no GPU needed
- **Edge devices** can be low-power (Raspberry Pi, NVR)

### Privacy
- **Raw images** never leave edge device network
- **Embeddings/HMACs** sent instead of PII
- **On-demand serving**: Policy fetches images only when needed

### Scalability
- **10+ edge devices** → **1 policy server**
- **Centralized tracking** across all cameras
- **Shared trust database** and visitor history

### Maintainability
- **Update policies** without touching edge code
- **Edge = dumb sensor** (simple, stable)
- **Policy = smart brain** (complex, evolving)

### Resilience
- **Fallback mode**: Edge continues if policy down
- **Local retention**: Images safe even if network fails
- **Eventual consistency**: Sync when connection restored

---

## Example Scenarios

### Scenario 1: Sheriff Arrives

| Step | Layer | Action |
|------|-------|--------|
| 1 | Edge | Camera detects person + vehicle |
| 2 | Edge | YOLO: person (0.95), vehicle (0.92) |
| 3 | Edge | OCR extracts plate: "SHERIFF1" |
| 4 | Edge | Color analysis: tan clothing |
| 5 | Edge | POST observations to policy |
| 6 | Policy | Check if "SHERIFF1" in trusted_plates |
| 7 | Policy | Add trust evidence: trusted_plate="sheriff" |
| 8 | Policy | Scene tracking: vehicle_entered |
| 9 | Policy | Intent classification: sheriff (0.95) |
| 10 | Policy | Match policy: sheriff_visitor |
| 11 | Policy | Execute: Send Telegram |
| 12 | Policy | Return: speak("Hello officer") |
| 13 | Edge | TTS playback: "Hello officer" |

### Scenario 2: Unknown Loiterer

| Step | Layer | Action |
|------|-------|--------|
| 1 | Edge | Camera detects person |
| 2 | Edge | YOLO: person (0.88) |
| 3 | Edge | Face recognition: no match |
| 4 | Edge | POST observations to policy |
| 5 | Policy | Scene tracking: person present 45s |
| 6 | Policy | Check trust: face unknown |
| 7 | Policy | Intent classification: unknown (0.6) |
| 8 | Policy | Match policy: loitering_alert |
| 9 | Policy | Execute: Send Telegram alert |
| 10 | Policy | Return: no TTS (silent) |

### Scenario 3: Package Delivery

| Step | Layer | Action |
|------|-------|--------|
| 1 | Edge | Camera detects person + package |
| 2 | Edge | YOLO: person (0.92), package (0.85) |
| 3 | Edge | Color analysis: brown uniform |
| 4 | Edge | POST observations to policy |
| 5 | Policy | Check if expecting delivery |
| 6 | Policy | Intent classification: delivery (0.88) |
| 7 | Policy | Match policy: delivery_expected |
| 8 | Policy | Execute: Log delivery time |
| 9 | Policy | Return: speak("Thank you!") |
| 10 | Edge | TTS playback: "Thank you!" |

---

## Common Mistakes

### ❌ Wrong: Running Policy Logic on Edge
```python
# edge/agent/camera_loop.py (DON'T DO THIS)
if plate_text == "SHERIFF1":  # Trust check on edge
    send_telegram("Sheriff arrived")
```
**Why wrong**: Trust database is centralized, edge doesn't have it.

### ✅ Right: Edge Sends Facts, Policy Decides
```python
# edge/agent/camera_loop.py (DO THIS)
evidence.append({
    "source": "ocr",
    "feature": "plate_text",
    "value": "SHERIFF1"  # Just the fact
})
send_to_policy_api(evidence)  # Let policy decide
```

---

### ❌ Wrong: Uploading All Images to Central
```python
# edge/agent/camera_loop.py (DON'T DO THIS)
with open(image_path, 'rb') as f:
    requests.post(policy_url, files={'image': f})  # Bandwidth waste
```
**Why wrong**: Every frame uploaded = massive bandwidth.

### ✅ Right: HTTP Server on Edge, Download on Demand
```python
# edge/agent/image_server.py (DO THIS)
image_server.start(port=8080)  # Serve locally
snapshot_url = f"http://edge-device:8080/{filename}"
send_to_policy_api(snapshot_url=snapshot_url)
# Policy downloads only if needed for Telegram
```

---

## Configuration Examples

### Edge Device (edge/agent/config.yaml)
```yaml
agent:
  camera_id: 1
  mode: doorbell

# Policy server location
policy_api:
  base_url: http://policy-server:8000

# Local capabilities
camera:
  rtsp_url: rtsp://camera/stream

# Image serving (not uploading!)
image_server:
  enabled: true
  port: 8080
```

### Policy Server (.env)
```bash
ECHOBELL_DB_PATH=/data/echoBell.db
TELEGRAM_BOT_TOKEN=your_token
```

---

## Quick Decision Tree

**Should this capability be on Edge or Policy?**

1. **Does it need physical hardware?** → Edge
2. **Does it need state across cameras?** → Policy
3. **Does it need trust database?** → Policy
4. **Is it heavy ML inference?** → Edge
5. **Is it a decision/action?** → Policy
6. **Is it privacy-sensitive?** → Keep on Edge
7. **Is it shared logic?** → Policy

---

## See Also

- **[TWO_LAYER_ARCHITECTURE.md](TWO_LAYER_ARCHITECTURE.md)** - Full two-layer guide
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Complete system architecture
- **[edge/agent/README.md](../edge/agent/README.md)** - Edge device setup
- **[central/policy-server/](../central/policy-server/)** - Policy server setup
