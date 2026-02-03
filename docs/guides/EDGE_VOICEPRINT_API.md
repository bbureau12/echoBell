# Edge Server Voiceprint API Specification

This document describes the HTTP API endpoint needed on edge devices to support speaker identification via SpeechBrain voiceprints.

## Overview

The central echoBell server needs edge devices to extract speaker voiceprints from audio files using SpeechBrain. The edge device should:

1. Run SpeechBrain ECAPA-TDNN model for speaker embeddings
2. Expose an HTTP endpoint for voiceprint extraction
3. Return 192-dimensional float32 embeddings

## Required Endpoint

### POST `/api/voiceprint/extract`

Extract speaker voiceprint embedding from an audio file.

**Request:**
```json
{
  "audio_path": "/path/to/audio.wav",
  "model_name": "speechbrain_ecapa"
}
```

**Request Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio_path` | string | Yes | Absolute path to audio file on edge device |
| `model_name` | string | Yes | Model identifier (currently: "speechbrain_ecapa") |

**Response (200 OK):**
```json
{
  "embedding": [0.123, -0.456, 0.789, ...],
  "duration_sec": 3.5,
  "quality_score": 0.95
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `embedding` | array[float] | 192-dimensional float32 embedding vector |
| `duration_sec` | float | Audio file duration in seconds |
| `quality_score` | float | Audio quality estimate (0-1), 1.0 = excellent |

**Error Responses:**

- `400 Bad Request` - Invalid audio file or unsupported format
- `404 Not Found` - Audio file does not exist
- `500 Internal Server Error` - Model loading or extraction failed

```json
{
  "error": "Audio file not found: /path/to/audio.wav"
}
```

## Implementation Guide

### 1. Install SpeechBrain

```bash
pip install speechbrain
pip install torchaudio
```

### 2. Download ECAPA-TDNN Model

The model will auto-download on first use, but you can pre-download:

```python
from speechbrain.pretrained import EncoderClassifier

classifier = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir="./pretrained_models/spkrec-ecapa-voxceleb"
)
```

**Model Details:**
- Name: `speechbrain/spkrec-ecapa-voxceleb`
- Architecture: ECAPA-TDNN (Emphasized Channel Attention, Propagation and Aggregation)
- Embedding dim: 192
- Trained on: VoxCeleb dataset
- Performance: State-of-the-art speaker verification

### 3. Example Implementation (FastAPI)

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
import torchaudio
import numpy as np
from speechbrain.pretrained import EncoderClassifier
from pathlib import Path

app = FastAPI()

# Load model once at startup (not per request)
print("Loading SpeechBrain ECAPA-TDNN model...")
classifier = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir="./pretrained_models/spkrec-ecapa-voxceleb"
)
print("Model loaded successfully")


class VoiceprintRequest(BaseModel):
    audio_path: str
    model_name: str = "speechbrain_ecapa"


class VoiceprintResponse(BaseModel):
    embedding: list[float]
    duration_sec: float
    quality_score: float


@app.post("/api/voiceprint/extract", response_model=VoiceprintResponse)
async def extract_voiceprint(request: VoiceprintRequest):
    """
    Extract speaker voiceprint embedding from audio file.
    
    Supports: WAV, MP3, FLAC, OGG formats
    Recommended: WAV, 16kHz, mono, 16-bit
    """
    audio_path = Path(request.audio_path)
    
    # Validate file exists
    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found: {request.audio_path}"
        )
    
    # Validate model name
    if request.model_name != "speechbrain_ecapa":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model: {request.model_name}"
        )
    
    try:
        # Load audio
        signal, sample_rate = torchaudio.load(str(audio_path))
        
        # Convert to mono if stereo
        if signal.shape[0] > 1:
            signal = torch.mean(signal, dim=0, keepdim=True)
        
        # Calculate duration
        duration_sec = signal.shape[1] / sample_rate
        
        # Extract embedding
        # SpeechBrain expects batch dimension: (batch, time)
        embeddings = classifier.encode_batch(signal)
        
        # Get first (and only) embedding, convert to numpy
        embedding = embeddings[0].cpu().numpy().flatten()
        
        # Estimate quality based on duration and signal characteristics
        quality_score = estimate_audio_quality(signal, sample_rate, duration_sec)
        
        return VoiceprintResponse(
            embedding=embedding.tolist(),
            duration_sec=float(duration_sec),
            quality_score=float(quality_score)
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract voiceprint: {str(e)}"
        )


def estimate_audio_quality(signal: torch.Tensor, sample_rate: int, duration_sec: float) -> float:
    """
    Estimate audio quality for speaker recognition.
    
    Factors:
    - Duration (optimal: 2-5 seconds)
    - SNR (signal-to-noise ratio)
    - Clipping detection
    
    Returns: Quality score 0-1
    """
    quality = 1.0
    
    # Duration scoring
    if duration_sec < 1.0:
        quality *= 0.5  # Too short
    elif duration_sec < 2.0:
        quality *= 0.8  # Short but usable
    elif duration_sec > 10.0:
        quality *= 0.9  # Long (may have silence/noise)
    
    # Check for clipping (values near -1 or 1)
    max_amplitude = torch.max(torch.abs(signal))
    if max_amplitude > 0.95:
        quality *= 0.7  # Likely clipped
    
    # Simple SNR estimate (not perfect but useful)
    # Assume last 10% of signal might be silence
    if duration_sec > 2.0:
        silence_portion = signal[:, -int(sample_rate * 0.1):]
        noise_level = torch.std(silence_portion)
        signal_level = torch.std(signal)
        
        if noise_level > 0:
            snr = signal_level / noise_level
            if snr < 5:
                quality *= 0.6  # Low SNR
            elif snr < 10:
                quality *= 0.8
    
    return quality


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model": "speechbrain/spkrec-ecapa-voxceleb",
        "embedding_dim": 192
    }


if __name__ == "__main__":
    import uvicorn
    
    # Run on all interfaces so central server can access
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

### 4. Run the Server

```bash
python edge_voiceprint_server.py
```

Server will be available at: `http://<edge-device-ip>:8001`

### 5. Test the Endpoint

```bash
# Health check
curl http://localhost:8001/health

# Extract voiceprint
curl -X POST http://localhost:8001/api/voiceprint/extract \
  -H "Content-Type: application/json" \
  -d '{
    "audio_path": "/path/to/test.wav",
    "model_name": "speechbrain_ecapa"
  }'
```

Expected response:
```json
{
  "embedding": [0.123, -0.456, ...],  // 192 floats
  "duration_sec": 3.5,
  "quality_score": 0.95
}
```

## Audio Format Requirements

### Supported Formats
- WAV (recommended)
- MP3
- FLAC
- OGG

### Optimal Specifications
- **Sample rate:** 16 kHz (model was trained on 16kHz)
- **Channels:** Mono (stereo will be auto-converted)
- **Bit depth:** 16-bit
- **Duration:** 2-5 seconds (minimum 1 second)
- **Format:** WAV PCM

### Audio Quality Tips
- Avoid clipping (keep levels below -3dB peak)
- Minimize background noise
- Single speaker only (no overlapping speech)
- Clear, natural speech (not whispered or shouted)
- Avoid music/loud background sounds

## Integration with echoBell Central Server

The central server will call this endpoint when:

1. **Storing voiceprints** - Enrolling trusted persons
2. **Matching speakers** - Identifying who is at the door

### Sequence Diagram

```
Edge Device                Central Server
    |                           |
    |<--- POST /api/voiceprint/extract
    |     {audio_path: "..."}   |
    |                           |
    | Load audio                |
    | Extract embedding         |
    | Calculate quality         |
    |                           |
    |--- 200 OK ---------------->|
    |    {embedding: [...],     |
    |     duration: 3.5,         |
    |     quality: 0.95}         |
    |                           |
    |                    Match against DB
    |                    Return: John (87%)
```

## Configuration in Central Server

Add to your camera configuration:

```sql
-- Update camera with edge server URL
UPDATE camera 
SET edge_url = 'http://192.168.1.50:8001'
WHERE id = 1;
```

Or in camera service:
```python
from packages.data.camera_service import CameraService

CameraService.create_camera(
    conn,
    name="Front Door",
    edge_url="http://192.168.1.50:8001",
    ...
)
```

## Performance Considerations

### Inference Time
- ECAPA-TDNN on CPU: ~100-200ms per audio file
- ECAPA-TDNN on GPU: ~20-50ms per audio file
- Network latency: ~5-20ms (local network)
- **Total latency:** ~100-300ms (acceptable for doorbell use case)

### Resource Usage
- **Model size:** ~15MB download
- **Memory:** ~500MB when loaded
- **CPU:** 1 core sufficient, multi-core speeds up batch processing
- **GPU:** Optional but recommended for <50ms inference

### Concurrency
- Model is thread-safe (use single instance)
- FastAPI handles concurrent requests automatically
- Recommended: Limit to 5 concurrent requests to avoid memory issues

```python
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio

# Semaphore to limit concurrent extractions
extraction_semaphore = asyncio.Semaphore(5)

@app.post("/api/voiceprint/extract")
async def extract_voiceprint(request: VoiceprintRequest):
    async with extraction_semaphore:
        # ... extraction code ...
```

## Troubleshooting

### Model fails to load
```
Error: Connection timeout when downloading model
```
**Solution:** Pre-download model:
```bash
python -c "from speechbrain.pretrained import EncoderClassifier; EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb', savedir='./models')"
```

### Embedding dimension mismatch
```
Error: Expected 192-dim embedding, got 256
```
**Solution:** Verify you're using ECAPA-TDNN, not X-vector:
```python
# Correct:
source="speechbrain/spkrec-ecapa-voxceleb"  # 192-dim

# Wrong:
source="speechbrain/spkrec-xvect-voxceleb"  # 512-dim
```

### Audio file format error
```
Error: [Errno 2] No such file or directory
```
**Solution:** 
- Use absolute paths: `/home/pi/audio/doorbell.wav`
- Check file permissions: `chmod 644 /path/to/audio.wav`
- Verify torchaudio backend: `torchaudio.list_audio_backends()`

### Low quality scores
```
Warning: quality_score = 0.3
```
**Causes:**
- Audio too short (<1 second)
- High background noise
- Clipping/distortion
- Low sample rate

**Solution:** Improve audio capture or adjust quality thresholds on central server.

## Security Considerations

### 1. Path Traversal Protection

```python
from pathlib import Path

def validate_audio_path(audio_path: str, allowed_dir: str = "/var/audio") -> Path:
    """Prevent directory traversal attacks."""
    path = Path(audio_path).resolve()
    allowed = Path(allowed_dir).resolve()
    
    if not str(path).startswith(str(allowed)):
        raise ValueError(f"Access denied: {audio_path}")
    
    return path
```

### 2. API Authentication (Recommended)

```python
from fastapi import Header, HTTPException

API_KEY = "your-secret-key-here"  # Store in environment variable

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.post("/api/voiceprint/extract", dependencies=[Depends(verify_api_key)])
async def extract_voiceprint(request: VoiceprintRequest):
    # ... extraction code ...
```

Central server configuration:
```python
# Add API key to requests
headers = {"X-API-Key": os.getenv("EDGE_API_KEY")}

async with session.post(
    f"{edge_url}/api/voiceprint/extract",
    json={"audio_path": audio_path, "model_name": model_name},
    headers=headers
) as response:
    # ... handle response ...
```

### 3. Rate Limiting

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/voiceprint/extract")
@limiter.limit("10/minute")  # Max 10 extractions per minute per IP
async def extract_voiceprint(request: VoiceprintRequest):
    # ... extraction code ...
```

## Example: Complete Production-Ready Server

See `examples/edge_voiceprint_server.py` for a complete implementation including:
- ✅ Model caching
- ✅ Error handling
- ✅ Path validation
- ✅ Quality estimation
- ✅ Health checks
- ✅ Logging
- ✅ Metrics

## Testing Checklist

- [ ] Model loads successfully on startup
- [ ] `/health` endpoint returns 200 OK
- [ ] Extract voiceprint from test WAV file
- [ ] Verify embedding is 192-dimensional
- [ ] Test with various audio formats (WAV, MP3, FLAC)
- [ ] Test with mono and stereo audio
- [ ] Test with different durations (1s, 3s, 10s)
- [ ] Verify quality scores make sense
- [ ] Test error handling (missing file, invalid format)
- [ ] Test concurrent requests (5+ simultaneous)
- [ ] Measure average latency (<300ms)
- [ ] Verify central server can connect and extract

## Support

If you encounter issues:

1. Check logs: `journalctl -u voiceprint-server -f`
2. Verify model loaded: `curl http://localhost:8001/health`
3. Test locally first: `curl -X POST http://localhost:8001/api/voiceprint/extract -d '{...}'`
4. Check network connectivity: `ping <edge-device-ip>`
5. Verify firewall rules: `sudo ufw status`

## References

- **SpeechBrain:** https://speechbrain.github.io/
- **ECAPA-TDNN Paper:** https://arxiv.org/abs/2005.07143
- **VoxCeleb Dataset:** https://www.robots.ox.ac.uk/~vgg/data/voxceleb/
- **FastAPI Docs:** https://fastapi.tiangolo.com/

---

**Quick Start:**
```bash
# Install
pip install speechbrain torchaudio fastapi uvicorn

# Save the example code above to edge_voiceprint_server.py

# Run
python edge_voiceprint_server.py

# Test
curl http://localhost:8001/health
```

**That's it!** The central echoBell server will handle the rest.
