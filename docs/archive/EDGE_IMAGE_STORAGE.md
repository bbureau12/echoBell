# Edge Device Image Storage for Telegram Alerts

## Overview

This guide shows how to store images on the edge device and send them via Telegram when unknown vehicles/persons are detected.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Edge Device (Raspberry Pi / Camera Agent)          │
│                                                      │
│  1. Detect object (vehicle/person)                  │
│  2. Save frame to local storage                     │
│  3. Send detection + image_path to policy server    │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼ HTTP POST
┌─────────────────────────────────────────────────────┐
│  Policy Server                                       │
│                                                      │
│  1. Evaluate policy conditions                      │
│  2. If unknown vehicle → trigger telegram action    │
│  3. Read image from edge device path                │
│  4. Send via Telegram bot with photo                │
└─────────────────────────────────────────────────────┘
```

## Implementation

### 1. Edge Device - Save Frame on Detection

```python
# In your camera agent (e.g., apps/camera-agent/main.py)

import cv2
import time
from pathlib import Path
from packages.perception.vision import snapshot_and_detect

# Configure storage
EDGE_IMAGE_DIR = Path("/var/echoBell/images")  # Or data/edge_images for dev
EDGE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

def process_frame(frame, camera_id, policy_api_url):
    """Process a frame and send detections to policy server"""
    
    # Run detection
    vision_result = snapshot_and_detect(frame)
    
    # Check if we detected vehicles
    has_vehicle = any(obj.label == 'car' for obj in vision_result.objects)
    
    # Save frame if vehicle detected
    image_path = None
    if has_vehicle:
        timestamp = int(time.time())
        filename = f"cam{camera_id}_{timestamp}.jpg"
        image_path = str(EDGE_IMAGE_DIR / filename)
        
        # Save the frame
        cv2.imwrite(image_path, frame)
        print(f"[EDGE] Saved frame: {image_path}")
    
    # Send observations to policy server
    observations = []
    for obj in vision_result.objects:
        obs = {
            "label": obj.label,
            "confidence": obj.conf,
            "bbox": obj.bbox,
            "image_path": image_path if obj.label == 'car' else None  # Attach image
        }
        observations.append(obs)
    
    # POST to policy server
    payload = {
        "camera_id": camera_id,
        "timestamp": timestamp,
        "observations": observations,
        "evidence": []  # Add any evidence items
    }
    
    response = requests.post(
        f"{policy_api_url}/observations",
        json=payload
    )
    
    return response.json()
```

### 2. Policy Server - Update ObservationRequest Model

```python
# In apps/policy-server/server.py

class Observation(BaseModel):
    """Single observation from camera."""
    label: str
    confidence: float
    bbox: list[float]
    image_path: Optional[str] = None  # ADD THIS - path to saved image on edge device

class ObservationRequest(BaseModel):
    """Observations from edge device sensor."""
    camera_id: int
    timestamp: int
    event_id: Optional[str] = None
    observations: list[Observation]
    evidence: list[EvidenceItem] = Field(default_factory=list)
```

### 3. Policy - Configure Telegram Action with Photo

```yaml
# config/policies.yaml

policies:
  - name: unknown_vehicle_alert
    description: Alert with photo when unknown vehicle detected
    conditions:
      all:
        - field: label
          operator: equals
          value: car
        - field: is_known_vehicle
          operator: equals
          value: false
    actions:
      - type: telegram
        message: "⚠️ Unknown vehicle detected at {camera_name}"
        priority: high
        send_photo: true  # Enable photo sending
        # photo_path will be set dynamically from observation.image_path
```

### 4. Policy Executor - Attach Image Path

```python
# In packages/policy/executor.py or action_handlers.py

async def execute_telegram_action(action, variables, context):
    """Execute telegram action with optional photo"""
    
    # Extract image path from context if available
    image_path = context.get('image_path')
    
    # If image exists and action wants photo, attach it
    if action.get('send_photo') and image_path:
        if os.path.exists(image_path):
            action['photo_path'] = image_path
            logger.info(f"[TELEGRAM] Attaching photo: {image_path}")
        else:
            logger.warning(f"[TELEGRAM] Image not found: {image_path}")
    
    # Send via Telegram (existing handler code)
    ...
```

## Alternative: Central Storage with SnapshotService

If you prefer to store images centrally on the policy server:

```python
# In apps/policy-server/server.py

@app.post("/observations")
async def receive_observations(request: ObservationRequest):
    """Receive observations from edge device"""
    
    snapshot_service = SnapshotService(output_dir="data/img_log")
    
    # Process each observation
    for obs in request.observations:
        if obs.label == 'car' and obs.image_path:
            # Edge device sends base64-encoded image or file upload
            # Save it centrally using SnapshotService
            
            # Decode image
            image_bytes = base64.b64decode(obs.image_data)
            image_array = np.frombuffer(image_bytes, dtype=np.uint8)
            frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            
            # Save snapshot
            metadata = SnapshotMetadata(
                camera_id=request.camera_id,
                timestamp=request.timestamp
            )
            
            filename, snapshot_id = snapshot_service.save_snapshot(
                conn, frame, metadata
            )
            
            # Use this filename in Telegram action
            obs.local_image_path = f"data/img_log/{filename}"
```

## Configuration

### Environment Variables

```bash
# .env or docker-compose.yml
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_ENABLED=true

# Edge device storage
EDGE_IMAGE_DIR=/var/echoBell/images
EDGE_IMAGE_RETENTION_DAYS=7  # Auto-cleanup old images
```

### Storage Considerations

1. **Edge Device Storage:**
   - **Pros:** Faster (no upload), lower bandwidth
   - **Cons:** Policy server must access edge filesystem (shared mount or NFS)
   
2. **Central Storage (SnapshotService):**
   - **Pros:** Centralized management, easier backup
   - **Cons:** Network overhead, requires image upload

3. **Hybrid Approach:**
   - Edge device saves locally for immediate use
   - Background job uploads to central storage
   - Cleanup policy removes edge images after N days

## Example Policy YAML

```yaml
# Full example with photo sending

policies:
  - name: unknown_vehicle_photo_alert
    description: Send photo of unknown vehicles via Telegram
    priority: 80
    status: active
    
    conditions:
      all:
        - field: label
          operator: equals
          value: car
        - field: plate_text
          operator: not_in_list
          value: known_plates  # From config or DB
    
    actions:
      - type: telegram
        message: |
          🚗 Unknown Vehicle Detected
          
          Camera: {camera_name}
          Time: {timestamp}
          Plate: {plate_text}
          Confidence: {confidence}%
        
        priority: high
        send_photo: true
        
      - type: log
        message: "Unknown vehicle: {plate_text}"
```

## Testing

```python
# tests/test_telegram_with_photo.py

import os
import cv2
import numpy as np
from packages.integrations.telegram import load_telegram_config, TelegramNotifier

def test_send_vehicle_photo():
    """Test sending vehicle detection photo via Telegram"""
    
    # Create test image
    test_image = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(test_image, "Unknown Vehicle ABC-123", (50, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    
    # Save to temp file
    temp_path = "data/test_vehicle.jpg"
    cv2.imwrite(temp_path, test_image)
    
    # Send via Telegram
    config = load_telegram_config()
    if not config:
        print("❌ Telegram not configured")
        return
    
    notifier = TelegramNotifier(config)
    success = notifier.send_photo(
        temp_path,
        caption="⚠️ Test: Unknown vehicle ABC-123 detected"
    )
    
    if success:
        print("✅ Photo sent successfully!")
    else:
        print("❌ Failed to send photo")
    
    # Cleanup
    os.remove(temp_path)

if __name__ == "__main__":
    test_send_vehicle_photo()
```

## Cleanup Script

```python
# scripts/cleanup_edge_images.py

import os
import time
from pathlib import Path

def cleanup_old_images(image_dir: str, retention_days: int = 7):
    """Remove images older than retention_days"""
    
    cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
    removed_count = 0
    
    for filepath in Path(image_dir).glob("*.jpg"):
        if filepath.stat().st_mtime < cutoff_time:
            filepath.unlink()
            removed_count += 1
    
    print(f"Cleaned up {removed_count} old images from {image_dir}")
    return removed_count

if __name__ == "__main__":
    cleanup_old_images("/var/echoBell/images", retention_days=7)
```

Add to cron:
```bash
# Run daily at 2 AM
0 2 * * * python /opt/echoBell/scripts/cleanup_edge_images.py
```

## See Also

- `packages/data/snapshot_service.py` - Central image storage
- `packages/integrations/telegram.py` - Telegram bot integration
- `packages/policy/action_handlers.py` - Action execution
- `tests/test_telegram_simple.py` - Telegram integration tests
