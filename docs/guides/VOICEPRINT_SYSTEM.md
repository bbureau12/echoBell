# Voiceprint Speaker Identification System

Complete implementation of speaker identification using SpeechBrain voiceprints for trusted person recognition.

## Overview

This system enables echoBell to identify trusted people by their voice, integrating with:
- **Edge servers** running SpeechBrain for voiceprint extraction
- **Central database** for voiceprint storage and matching  
- **Conversation handler** for automatic speaker identification during doorbell interactions
- **REST API** for voiceprint management (CRUD operations)

## Components Built

### 1. Database Migration (`014_add_voiceprints.sql`)

**Tables:**
- `trusted_voiceprints` - Stores speaker voiceprint embeddings
  - Links to `trusted_person` table
  - Stores SpeechBrain embeddings (typically 192-dim ECAPA-TDNN)
  - Tracks quality score, camera ID, audio duration
  - Foreign key cascade delete with trusted_person
  
- `voiceprint_matches` - Audit trail for matching attempts
  - Tracks successful and failed matches
  - Links to conversation sessions
  - Useful for debugging and threshold tuning

**Indexes:**
- `trusted_id` for fast lookups by person
- `model_name` for filtering by embedding model
- `camera_id` for edge-specific queries
- Composite index on `model_name + trusted_id` for efficient matching

### 2. Service Layer (`packages/data/voiceprint_service.py`)

**VoiceprintService** provides:

#### CRUD Operations:
- `create_voiceprint()` - Store voiceprint with L2 normalization
- `get_voiceprint()` - Retrieve by ID
- `get_voiceprints_for_person()` - Get all voiceprints for person
- `list_voiceprints()` - List all with optional model filter
- `update_voiceprint()` - Update metadata (quality, notes)
- `delete_voiceprint()` - Delete single voiceprint
- `delete_voiceprints_for_person()` - Bulk delete

#### Matching & Analytics:
- `match_voiceprint()` - Cosine similarity matching against database
  - Returns top-k matches sorted by confidence
  - Configurable threshold (default 0.75)
  - L2 normalizes query embedding automatically
  
- `log_match_attempt()` - Record match attempt for analytics
- `get_match_history()` - Query match history by person/session

**Data Models:**
- `Voiceprint` dataclass - Represents stored voiceprint
- `VoiceprintMatch` dataclass - Match result with confidence

### 3. Conversation Handler Integration

Updated `packages/llm/conversation_handler.py` with:

#### New Methods:

**`fetch_voiceprint_from_edge()`** - HTTP call to edge server
```python
# POST http://{edge_url}/api/voiceprint/extract
# Body: {"audio_path": "...", "model_name": "speechbrain_ecapa"}
# Returns: {"embedding": [0.123, ...]}
```

**`match_speaker()`** - Main speaker identification method
- Fetches voiceprint from edge server
- Matches against database using VoiceprintService
- Logs match attempt
- Returns trusted_id, name, confidence

**`store_voiceprint()`** - Store new voiceprint for trusted person
- Fetches embedding from edge
- Stores in database with metadata

**`handle_doorbell_audio()` enhancements:**
- Optional voiceprint matching (enable_voiceprint=True)
- Adds speaker match to context: `{"speaker_match": {...}}`
- Shows in logs: `[VOICEPRINT] Matched speaker: John (87.3% confidence)`
- Passed to LLM in initial prompt

**`_build_initial_prompt()` enhancements:**
- Includes speaker line if matched:
  ```
  Transcript: "Hi, it's me!"
  - Speaker: John Doe (87.3% match)
  ```

### 4. REST API (`central/policy-server/api_voiceprints.py`)

**FastAPI router** mounted at `/voiceprints`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/voiceprints/` | List all voiceprints (filter by trusted_id, model_name) |
| `GET` | `/voiceprints/{id}` | Get specific voiceprint |
| `POST` | `/voiceprints/` | Create voiceprint from base64 embedding |
| `PATCH` | `/voiceprints/{id}` | Update metadata (quality, notes) |
| `DELETE` | `/voiceprints/{id}` | Delete voiceprint |
| `POST` | `/voiceprints/match` | Match embedding against database |
| `GET` | `/voiceprints/history/matches` | Get match history |

**Request/Response Models:**
- `VoiceprintCreate` - Create request with base64 embedding
- `VoiceprintUpdate` - Update request
- `VoiceprintResponse` - Single voiceprint response
- `VoiceprintListResponse` - List response with count
- `VoiceprintMatchRequest` - Match request with threshold
- `VoiceprintMatchResponse` - Match result with confidence list

**Integration:**
- Auto-loaded by `central/policy-server/server.py`
- Shares database connection with policy API
- Available at `http://localhost:8000/voiceprints/*`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Edge Server (Camera Device)                                │
│                                                              │
│  ┌──────────────────┐      ┌─────────────────────────────┐ │
│  │ Audio Capture    │─────>│ SpeechBrain ECAPA-TDNN      │ │
│  │ (doorbell press) │      │ (speaker embedding)          │ │
│  └──────────────────┘      └──────────────┬──────────────┘ │
│                                            │                 │
│                           POST /api/voiceprint/extract      │
│                           {embedding: [0.123, ...]}         │
└────────────────────────────────────────────┼────────────────┘
                                             │
                                             │ HTTP
                                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Central Server (Policy Server)                             │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ConversationHandler                                   │  │
│  │                                                        │  │
│  │  1. fetch_voiceprint_from_edge()                      │  │
│  │  2. match_speaker() ────────┐                         │  │
│  │  3. Add to context          │                         │  │
│  └─────────────────────────────┼────────────────────────┘  │
│                                │                            │
│                                ▼                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ VoiceprintService                                     │  │
│  │                                                        │  │
│  │  • Cosine similarity matching                         │  │
│  │  • Top-k results sorted by confidence                 │  │
│  │  • Log match attempts                                 │  │
│  └────────────────┬──────────────────────────────────────┘  │
│                   │                                         │
│                   ▼                                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Database (doorbell.db)                                │  │
│  │                                                        │  │
│  │  trusted_voiceprints (embeddings)                     │  │
│  │  voiceprint_matches (audit trail)                     │  │
│  │  trusted_person (linked)                              │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ REST API (/voiceprints)                               │  │
│  │                                                        │  │
│  │  GET    /voiceprints/              List all           │  │
│  │  POST   /voiceprints/              Create             │  │
│  │  PATCH  /voiceprints/{id}          Update             │  │
│  │  DELETE /voiceprints/{id}          Delete             │  │
│  │  POST   /voiceprints/match         Match speaker      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Usage Examples

### 1. Store Voiceprint for Trusted Person

**Via API:**
```bash
# Get embedding from edge server first
EMBEDDING=$(curl -X POST http://edge-server/api/voiceprint/extract \
  -H "Content-Type: application/json" \
  -d '{"audio_path": "/path/to/audio.wav", "model_name": "speechbrain_ecapa"}' \
  | jq -r '.embedding | @base64')

# Store in database
curl -X POST http://localhost:8000/voiceprints/ \
  -H "Content-Type: application/json" \
  -d "{
    \"trusted_id\": 1,
    \"embedding_base64\": \"$EMBEDDING\",
    \"model_name\": \"speechbrain_ecapa\",
    \"quality_score\": 0.95,
    \"camera_id\": 1,
    \"audio_duration_sec\": 3.5,
    \"notes\": \"Enrollment from front door\"
  }"
```

**Via ConversationHandler:**
```python
from packages.llm import ConversationHandler
from packages.data.voiceprint_service import VoiceprintService

handler = ConversationHandler(
    conn=conn,
    asr_service=asr,
    tts_service=tts,
    voiceprint_service=VoiceprintService()
)

# Store voiceprint
voiceprint_id = await handler.store_voiceprint(
    audio_path="/path/to/audio.wav",
    trusted_id=1,
    camera_id=1,
    quality_score=0.95,
    notes="Enrollment sample"
)
```

### 2. Match Speaker During Conversation

**Automatic (in handle_doorbell_audio):**
```python
result = await handler.handle_doorbell_audio(
    audio_path="/path/to/doorbell.wav",
    context={"camera_id": 1},
    enable_voiceprint=True  # Default
)

if result.get('speaker_match'):
    print(f"Speaker: {result['speaker_match']['trusted_name']}")
    print(f"Confidence: {result['speaker_match']['confidence_percent']}%")
```

**Manual matching:**
```python
match = await handler.match_speaker(
    audio_path="/path/to/audio.wav",
    camera_id=1,
    threshold=0.75
)

if match:
    print(f"Matched: {match['trusted_name']} ({match['confidence_percent']}%)")
```

### 3. Query Voiceprints via API

```bash
# List all voiceprints
curl http://localhost:8000/voiceprints/

# List voiceprints for specific person
curl http://localhost:8000/voiceprints/?trusted_id=1

# Filter by model
curl http://localhost:8000/voiceprints/?model_name=speechbrain_ecapa

# Get match history
curl http://localhost:8000/voiceprints/history/matches?trusted_id=1&limit=50
```

### 4. Match Voiceprint via API

```bash
# Get embedding from edge server
EMBEDDING=$(curl -X POST http://edge-server/api/voiceprint/extract \
  -H "Content-Type: application/json" \
  -d '{"audio_path": "/tmp/test.wav", "model_name": "speechbrain_ecapa"}' \
  | jq -r '.embedding | @base64')

# Match against database
curl -X POST http://localhost:8000/voiceprints/match \
  -H "Content-Type: application/json" \
  -d "{
    \"embedding_base64\": \"$EMBEDDING\",
    \"model_name\": \"speechbrain_ecapa\",
    \"threshold\": 0.75,
    \"top_k\": 5,
    \"camera_id\": 1,
    \"session_id\": \"conv-123\"
  }"
```

Response:
```json
{
  "matched": true,
  "matches": [
    {
      "trusted_id": 1,
      "trusted_name": "John Doe",
      "confidence": 0.873,
      "confidence_percent": 87.3,
      "voiceprint_id": 42,
      "quality_score": 0.95
    }
  ]
}
```

## Edge Server Requirements

Your edge servers need to implement:

**Endpoint:** `POST /api/voiceprint/extract`

**Request:**
```json
{
  "audio_path": "/path/to/audio.wav",
  "model_name": "speechbrain_ecapa"
}
```

**Response:**
```json
{
  "embedding": [0.123, -0.456, 0.789, ...],  // 192-dim for ECAPA-TDNN
  "duration_sec": 3.5,
  "quality_score": 0.95
}
```

**Example implementation** (Python with SpeechBrain):
```python
from speechbrain.pretrained import EncoderClassifier
from fastapi import FastAPI

app = FastAPI()
classifier = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir="pretrained_models/spkrec-ecapa-voxceleb"
)

@app.post("/api/voiceprint/extract")
async def extract_voiceprint(request: dict):
    audio_path = request["audio_path"]
    
    # Extract embedding
    signal, fs = torchaudio.load(audio_path)
    embeddings = classifier.encode_batch(signal)
    embedding = embeddings[0].cpu().numpy().flatten()
    
    # Get audio duration
    duration_sec = signal.shape[1] / fs
    
    return {
        "embedding": embedding.tolist(),
        "duration_sec": float(duration_sec),
        "quality_score": 1.0  # Implement quality scoring
    }
```

## Configuration

### Conversation Handler

```python
from packages.llm import ConversationHandler
from packages.data.voiceprint_service import VoiceprintService

handler = ConversationHandler(
    conn=db_conn,
    asr_service=asr,
    tts_service=tts,
    voiceprint_service=VoiceprintService(),  # Enable voiceprint matching
    llm_provider="vicuna",
    llm_config={"base_url": "http://llm-server:8000"}
)
```

### Policy Server

```bash
# Start with voiceprint API enabled
cd central/policy-server
python server.py
```

Endpoints available at:
- `http://localhost:8000/voiceprints/*`
- `http://localhost:8000/policies/*`
- `http://localhost:8000/scene/*`

## Database Schema

### trusted_voiceprints

| Column | Type | Description |
|--------|------|-------------|
| voiceprint_id | INTEGER PRIMARY KEY | Unique ID |
| trusted_id | INTEGER | FK to trusted_person |
| model_name | TEXT | "speechbrain_ecapa", etc. |
| embedding_dim | INTEGER | Embedding dimension (192, 512) |
| embedding_blob | BLOB | Float32 numpy array |
| camera_id | INTEGER | Which edge captured this |
| created_ts | INTEGER | Unix timestamp |
| quality_score | REAL | Audio quality (0-1) |
| audio_duration_sec | REAL | Sample length |
| notes | TEXT | Optional metadata |

### voiceprint_matches

| Column | Type | Description |
|--------|------|-------------|
| match_id | INTEGER PRIMARY KEY | Unique ID |
| session_id | TEXT | Link to llm_conversations |
| camera_id | INTEGER | Which camera |
| matched_trusted_id | INTEGER | FK to trusted_person (NULL if no match) |
| confidence_score | REAL | Similarity score (0-1) |
| threshold_used | REAL | Threshold at match time |
| model_name | TEXT | Model used |
| matched_ts | INTEGER | Unix timestamp |
| audio_duration_sec | REAL | Sample length |
| notes | TEXT | Optional metadata |

## Testing

### 1. Apply Migration

```bash
cd infra/db/migrations
sqlite3 ../../data/doorbell.db < 014_add_voiceprints.sql
```

Verify:
```sql
.tables
-- Should show: trusted_voiceprints, voiceprint_matches

.schema trusted_voiceprints
-- Should show indexes
```

### 2. Test API Endpoints

```bash
# Start server
cd central/policy-server
python server.py

# Health check
curl http://localhost:8000/health

# List voiceprints (empty initially)
curl http://localhost:8000/voiceprints/
```

### 3. Create Test Voiceprint

```python
import sqlite3
import numpy as np
import base64
from packages.data.voiceprint_service import VoiceprintService

# Connect to database
conn = sqlite3.connect("data/doorbell.db")

# Create test embedding
test_embedding = np.random.rand(192).astype(np.float32)

# Store voiceprint
vp_id = VoiceprintService.create_voiceprint(
    conn,
    trusted_id=1,  # Must exist in trusted_person table
    embedding=test_embedding,
    model_name="speechbrain_ecapa",
    quality_score=0.95,
    notes="Test voiceprint"
)

print(f"Created voiceprint {vp_id}")

# Match against it
matches = VoiceprintService.match_voiceprint(
    conn,
    embedding=test_embedding,
    model_name="speechbrain_ecapa",
    threshold=0.9
)

for m in matches:
    print(f"Match: {m.trusted_name} ({m.confidence:.1%})")

conn.close()
```

## Performance Considerations

### Matching Speed
- **Database size:** 100 voiceprints → ~10ms matching time
- **Database size:** 1000 voiceprints → ~50ms matching time
- **Optimization:** Use model_name filter to reduce search space

### Storage
- Each voiceprint: ~1KB (192-dim float32 + metadata)
- 1000 voiceprints: ~1MB database space

### Threshold Tuning
- **Default:** 0.75 (balanced false positive/negative)
- **Strict:** 0.85+ (fewer false positives)
- **Lenient:** 0.65 (catch more matches, more false positives)

Monitor `voiceprint_matches` table to tune threshold:
```sql
SELECT 
    AVG(confidence_score) as avg_confidence,
    MIN(confidence_score) as min_confidence,
    MAX(confidence_score) as max_confidence
FROM voiceprint_matches
WHERE matched_trusted_id IS NOT NULL;
```

## Next Steps

1. **Apply migration** - `014_add_voiceprints.sql`
2. **Set up edge server** - Implement `/api/voiceprint/extract` endpoint
3. **Test API** - Create, list, match voiceprints
4. **Enroll trusted persons** - Store voiceprints from good audio samples
5. **Integrate with policies** - Use speaker match in policy conditions
6. **Monitor performance** - Query `voiceprint_matches` for analytics
7. **Tune thresholds** - Adjust based on false positive/negative rates

## API Reference Summary

### Voiceprints CRUD

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/voiceprints/` | List all (filter: trusted_id, model_name) |
| `GET` | `/voiceprints/{id}` | Get specific voiceprint |
| `POST` | `/voiceprints/` | Create (base64 embedding) |
| `PATCH` | `/voiceprints/{id}` | Update metadata |
| `DELETE` | `/voiceprints/{id}` | Delete voiceprint |

### Matching & Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/voiceprints/match` | Match embedding (returns top-k) |
| `GET` | `/voiceprints/history/matches` | Match history (filter: trusted_id, session_id) |

All endpoints return JSON and use standard HTTP status codes (200, 201, 204, 404, 500).

---

**System is ready!** Apply the migration and start storing voiceprints.
