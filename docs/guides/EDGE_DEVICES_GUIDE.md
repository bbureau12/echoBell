# Edge Device Guide - Image Serving & Storage

## Overview

This guide covers how edge devices (cameras, doorbells) handle image storage and serving for the central policy server and Telegram alerts.

**Problem**: The policy server (central) needs to access images saved by the edge device to send them via Telegram.

**Solutions**:
1. Network File Share (LAN deployments)
2. HTTP Server on Edge (recommended)
3. Upload to Central (remote cameras)
4. Base64 in POST (small images only)

---

## Architecture Options

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Network File Share** | Simple, no extra code | Requires SMB/NFS setup | LAN deployments |
| **Upload to Central** | Clean architecture | Bandwidth overhead | Remote cameras |
| **HTTP Server on Edge** | Low bandwidth, on-demand | Edge must run web server | Mixed environments |
| **Base64 in POST** | No file system needed | Large payloads, encoding cost | Small images only |

---

## Option 1: Network File Share (LAN Deployments)

Edge device exposes a file share that the policy server mounts.

### Architecture

```
┌─────────────────────────────────────┐
│  Edge Device (192.168.1.100)        │
│                                     │
│  /var/echoBell/images/              │
│    ├── cam1_1234567890.jpg          │
│    └── cam1_1234567891.jpg          │
│                                     │
│  Samba/NFS Server                   │
│    Share: \\192.168.1.100\images   │
└─────────────────────────────────────┘
         │
         │ Network mount
         ▼
┌─────────────────────────────────────┐
│  Policy Server                       │
│                                     │
│  Mount: /mnt/edge_images/           │
│    (points to edge device share)    │
│                                     │
│  Telegram reads:                    │
│  /mnt/edge_images/cam1_xxx.jpg     │
└─────────────────────────────────────┘
```

### Implementation

**On Edge Device (Linux/Raspberry Pi):**

```bash
# Install Samba
sudo apt-get install samba samba-common-bin

# Create shared directory
sudo mkdir -p /var/echoBell/images
sudo chmod 777 /var/echoBell/images

# Configure Samba (/etc/samba/smb.conf)
sudo nano /etc/samba/smb.conf
```

Add this section:

```ini
[echoBell_images]
   path = /var/echoBell/images
   browseable = yes
   read only = yes
   guest ok = yes
   create mask = 0644
```

```bash
# Restart Samba
sudo systemctl restart smbd

# Test from policy server
smbclient -L //192.168.1.100 -N
```

**On Policy Server (Linux):**

```bash
# Install cifs-utils
sudo apt-get install cifs-utils

# Create mount point
sudo mkdir -p /mnt/edge_images

# Mount the share
sudo mount -t cifs //192.168.1.100/echoBell_images /mnt/edge_images -o guest,ro

# Auto-mount on boot (/etc/fstab)
echo "//192.168.1.100/echoBell_images /mnt/edge_images cifs guest,ro,_netdev 0 0" | sudo tee -a /etc/fstab
```

**On Policy Server (Windows):**

```powershell
# Map network drive
net use Z: \\192.168.1.100\echoBell_images

# Update policy server config to use Z:\
```

---

## Option 2: HTTP Server on Edge (Recommended)

Edge device runs a lightweight HTTP server to serve images on-demand.

### Architecture

```
┌─────────────────────────────────────┐
│  Edge Device (192.168.1.100:5000)   │
│                                     │
│  ┌────────────────────────────┐    │
│  │  HTTP Image Server         │    │
│  │  GET /images/<filename>    │    │
│  └────────────────────────────┘    │
│             │                       │
│             ▼                       │
│  /var/echoBell/images/              │
│    ├── cam1_1234567890.jpg          │
│    └── cam1_1234567891.jpg          │
└─────────────────────────────────────┘
         │
         │ HTTP GET
         ▼
┌─────────────────────────────────────┐
│  Policy Server                       │
│                                     │
│  Fetch: http://192.168.1.100:5000/  │
│         images/cam1_1234567890.jpg  │
│                                     │
│  Download → Send to Telegram        │
└─────────────────────────────────────┘
```

### Implementation

**Edge Device: HTTP Image Server**

The unified edge agent already includes this! See `edge/agent/image_server.py`:

```python
# edge/agent/image_server.py (already exists!)

from flask import Flask, send_file, abort
from pathlib import Path

app = Flask(__name__)
IMAGE_DIR = Path("data/img_log")

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve image file"""
    filepath = IMAGE_DIR / filename
    if not filepath.exists():
        abort(404)
    return send_file(str(filepath), mimetype='image/jpeg')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

**Edge Device: Start Image Server**

```python
# In edge/agent/main.py (already integrated!)

from image_server import start_image_server

# Start image server in background thread
start_image_server(
    image_dir="data/img_log",
    port=5000,
    cleanup_interval=3600  # Clean up old images every hour
)
```

**Policy Server: Fetch Images via HTTP**

```python
# In central/policy-server/server.py (add this helper)

import requests
from pathlib import Path

def fetch_edge_image(camera_id: int, filename: str) -> Path:
    """Download image from edge device HTTP server"""
    
    # Get edge device URL from config
    edge_url = get_edge_device_url(camera_id)  # e.g., "http://192.168.1.100:5000"
    
    # Download image
    url = f"{edge_url}/images/{filename}"
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    
    # Save to temp file
    temp_path = Path(f"/tmp/edge_images/{filename}")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(response.content)
    
    return temp_path

# Usage in Telegram handler
photo_path = fetch_edge_image(camera_id=1, filename="cam1_1234567890.jpg")
notifier.send_photo(photo_path, caption=message)
```

---

## Option 3: Upload to Central

Edge device uploads images to central server during observation POST.

### Implementation

**Edge Device: Upload Image**

```python
# In edge/agent/camera_loop.py

import requests

def send_observation_with_image(vision_result, camera_id, policy_api_url):
    """Send observation and upload image"""
    
    # Prepare observation payload
    payload = {
        "camera_id": camera_id,
        "timestamp": int(time.time()),
        "observations": [...]
    }
    
    # Upload image if exists
    files = {}
    if vision_result.snapshot_path:
        with open(vision_result.snapshot_path, 'rb') as f:
            files['image'] = f.read()
    
    response = requests.post(
        f"{policy_api_url}/observations",
        json=payload,
        files=files
    )
    
    return response.json()
```

**Central Server: Receive Upload**

```python
# In central/policy-server/server.py

from fastapi import File, UploadFile

@app.post("/observations")
async def receive_observations(
    request: ObservationRequest,
    image: UploadFile = File(None)
):
    """Receive observations with optional image upload"""
    
    # Save uploaded image
    if image:
        image_path = Path(f"data/uploads/{request.camera_id}_{request.timestamp}.jpg")
        image_path.write_bytes(await image.read())
        
        # Store path for later use
        request.image_path = str(image_path)
    
    # Process observations...
```

---

## Quick Start: Sending Photos via Telegram

Your system already has all the pieces! Here's how to connect them:

### Step 1: Update Your Policy

```yaml
# config/policies.yaml

policies:
  - name: unknown_vehicle_photo_alert
    description: Send photo when unknown vehicle detected
    priority: 80
    status: active
    
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
        message: "🚗 Unknown vehicle detected!\n📸 See photo attached"
        priority: high
        send_photo: true  # <-- This is the key!
```

### Step 2: Ensure Snapshot Path is Available

Your camera agent already does this in `edge/agent/camera_loop.py`:

```python
# Snapshot is already saved and path is available!
vision_result = snapshot_and_detect(frame)
# vision_result.snapshot_path contains the image path
```

### Step 3: Pass Snapshot to Policy Context

In your policy executor, ensure the snapshot path gets to the action handler:

```python
# In packages/policy/executor.py

context = {
    'camera_id': camera_id,
    'timestamp': timestamp,
    'snapshot_path': vision_result.snapshot_path,  # Add this!
    'track_key': track_key
}

results = await action_executor.execute_actions(
    actions=policy.actions,
    variables=variables,
    context=context
)
```

### Step 4: Action Handler Uses Snapshot

The Telegram action handler is already configured to use it:

```python
# In packages/policy/action_handlers.py (line 236-238)

send_photo = action.get('send_photo', False)
photo_path = context.get('snapshot_path')  # Gets path from context

if send_photo and photo_path:
    success = notifier.send_photo(photo_path, caption=message)
```

**That's it!** The system will now automatically send photos with Telegram alerts.

---

## Image Cleanup

The edge agent's image server includes automatic cleanup:

```python
# In edge/agent/image_server.py

def cleanup_old_images(image_dir: Path, max_age_hours: int = 24):
    """Delete images older than max_age_hours"""
    cutoff = time.time() - (max_age_hours * 3600)
    
    for img in image_dir.glob("*.jpg"):
        if img.stat().st_mtime < cutoff:
            img.unlink()
            print(f"[CLEANUP] Deleted old image: {img.name}")
```

Configure in `edge/agent/config.yaml`:

```yaml
image_server:
  enabled: true
  port: 5000
  cleanup_interval_hours: 1
  max_image_age_hours: 24
```

---

## Troubleshooting

**Image not found errors:**
- Check edge device image server is running: `curl http://192.168.1.100:5000/health`
- Verify snapshot path exists: `ls data/img_log/`
- Check policy server can reach edge: `ping 192.168.1.100`

**Telegram photo upload fails:**
- File size > 10MB (Telegram limit) - resize images
- Invalid file format - ensure JPEG/PNG
- Network timeout - increase timeout in config

**Permission errors:**
- Check file permissions: `chmod 644 data/img_log/*.jpg`
- Check directory permissions: `chmod 755 data/img_log/`

---

## See Also

- [edge/agent/README.md](../../edge/agent/README.md) - Edge agent configuration
- [TELEGRAM_INTEGRATION.md](../TELEGRAM_INTEGRATION.md) - Telegram bot setup
- [POLICY_REFERENCE.md](../POLICY_REFERENCE.md) - Policy configuration
