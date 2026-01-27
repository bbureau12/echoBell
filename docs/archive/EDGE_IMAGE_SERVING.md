# Edge Device Image Serving Options

## Problem Statement

The policy server (central) needs to access images saved by the edge device (camera/Raspberry Pi) to send them via Telegram. How does the central server get the image?

## Option Comparison

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Network File Share** | Simple, no extra code | Requires SMB/NFS setup | LAN deployments |
| **Upload to Central** | Clean architecture | Bandwidth overhead | Remote cameras |
| **HTTP Server on Edge** | Low bandwidth, on-demand | Edge must run web server | Mixed environments |
| **Base64 in POST** | No file system needed | Large payloads, encoding cost | Small images only |

---

## Option 1: Network File Share (Recommended for LAN)

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

# Or in PowerShell
New-PSDrive -Name "Z" -PSProvider FileSystem -Root "\\192.168.1.100\echoBell_images" -Persist
```

**Update Python Code:**

```python
# apps/camera-agent/loop.py (edge device)
EDGE_IMAGE_DIR = "/var/echoBell/images"  # Local path on edge

# Save image locally
image_path = f"{EDGE_IMAGE_DIR}/cam{camera_id}_{timestamp}.jpg"
cv2.imwrite(image_path, frame)

# Send path to policy server (relative to mount point)
observations = [{
    "label": "car",
    "snapshot_path": f"cam{camera_id}_{timestamp}.jpg"  # Just filename!
}]

# ----

# packages/policy/action_handlers.py (policy server)
MOUNT_PREFIX = "/mnt/edge_images"  # Where edge share is mounted

async def execute_telegram_action(...):
    # Construct full path from filename
    filename = context.get('snapshot_path')
    full_path = f"{MOUNT_PREFIX}/{filename}"
    
    if os.path.exists(full_path):
        notifier.send_photo(full_path, caption=message)
```

### Pros & Cons

✅ **Pros:**
- Simple, no extra services
- Low bandwidth (read on-demand)
- Works for multiple edge devices
- OS handles caching/buffering

❌ **Cons:**
- Only works on LAN (not over internet)
- Requires SMB/NFS setup
- Edge device must be always accessible
- Security concerns (file share exposure)

---

## Option 2: Upload Image to Central Server

Edge device POSTs the image to policy server immediately.

### Architecture

```
┌─────────────────────────────────────┐
│  Edge Device                         │
│                                     │
│  1. Detect vehicle                  │
│  2. Save image locally              │
│  3. Upload via HTTP POST            │
└──────────┬──────────────────────────┘
           │
           │ POST /upload_image
           │ (multipart/form-data)
           ▼
┌─────────────────────────────────────┐
│  Policy Server                       │
│                                     │
│  1. Receive image upload            │
│  2. Save to data/img_log/           │
│  3. Return image ID                 │
│                                     │
│  Later: Send via Telegram           │
└─────────────────────────────────────┘
```

### Implementation

**Policy Server - Add Upload Endpoint:**

```python
# apps/policy-server/server.py

from fastapi import File, UploadFile
from packages.data.snapshot_service import SnapshotService

snapshot_service = SnapshotService(output_dir="data/img_log")

@app.post("/upload_image")
async def upload_image(
    camera_id: int,
    timestamp: int,
    file: UploadFile = File(...)
):
    """Receive image upload from edge device"""
    
    # Read uploaded image
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Save using SnapshotService
    conn = get_db_connection()
    metadata = SnapshotMetadata(
        camera_id=camera_id,
        timestamp=timestamp
    )
    
    filename, snapshot_id = snapshot_service.save_snapshot(
        conn, image, metadata
    )
    
    conn.close()
    
    return {
        "snapshot_id": snapshot_id,
        "filename": filename,
        "path": f"data/img_log/{filename}"
    }
```

**Edge Device - Upload Image:**

```python
# apps/camera-agent/loop.py

import requests

def process_and_upload(frame, camera_id, policy_server_url):
    """Detect vehicle and upload image to central server"""
    
    vision = snapshot_and_detect(frame)
    
    if vision.vehicle_present:
        timestamp = int(time.time())
        
        # Encode image as JPEG
        _, buffer = cv2.imencode('.jpg', frame)
        
        # Upload to policy server
        files = {'file': ('image.jpg', buffer.tobytes(), 'image/jpeg')}
        data = {
            'camera_id': camera_id,
            'timestamp': timestamp
        }
        
        upload_response = requests.post(
            f"{policy_server_url}/upload_image",
            files=files,
            data=data
        )
        
        result = upload_response.json()
        snapshot_path = result['path']  # e.g., "data/img_log/abc-123.jpg"
        
        # Now send observation with snapshot path
        observations = [{
            "label": "car",
            "confidence": 0.95,
            "snapshot_path": snapshot_path  # Central server path
        }]
        
        requests.post(
            f"{policy_server_url}/observations",
            json={
                "camera_id": camera_id,
                "observations": observations,
                "evidence": []
            }
        )
```

### Pros & Cons

✅ **Pros:**
- Works over internet (remote cameras)
- Clean separation of concerns
- Central backup of all images
- No file sharing needed

❌ **Cons:**
- Higher bandwidth usage
- Double storage (edge + central)
- Upload latency
- Edge must handle upload failures

---

## Option 3: HTTP Server on Edge Device

Edge device runs a simple HTTP server, policy server fetches on-demand.

### Architecture

```
┌─────────────────────────────────────┐
│  Edge Device                         │
│                                     │
│  1. Save image locally              │
│  2. Run HTTP server on :8080        │
│  3. Serve images on request         │
│                                     │
│  GET /images/cam1_xxx.jpg           │
└──────────┬──────────────────────────┘
           │
           │ HTTP GET (on-demand)
           ▼
┌─────────────────────────────────────┐
│  Policy Server                       │
│                                     │
│  1. Get observation with URL        │
│  2. When sending telegram:          │
│     - Download from edge device     │
│     - Send to Telegram              │
└─────────────────────────────────────┘
```

### Implementation

**Edge Device - Simple HTTP Server:**

```python
# apps/camera-agent/image_server.py

from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import threading

class ImageHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="/var/echoBell/images", **kwargs)
    
    def log_message(self, format, *args):
        # Suppress logging
        pass

def start_image_server(port=8080):
    """Start HTTP server to serve images"""
    server = HTTPServer(('0.0.0.0', port), ImageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[IMAGE_SERVER] Started on port {port}")
    return server

# In your camera agent main:
start_image_server(port=8080)
```

**Edge Device - Send Image URL:**

```python
# apps/camera-agent/loop.py

EDGE_DEVICE_IP = "192.168.1.100"  # Or get dynamically
EDGE_HTTP_PORT = 8080

# Save image locally
filename = f"cam{camera_id}_{timestamp}.jpg"
local_path = f"/var/echoBell/images/{filename}"
cv2.imwrite(local_path, frame)

# Send URL to policy server
image_url = f"http://{EDGE_DEVICE_IP}:{EDGE_HTTP_PORT}/images/{filename}"

observations = [{
    "label": "car",
    "snapshot_path": image_url  # HTTP URL instead of file path!
}]
```

**Policy Server - Download on Demand:**

```python
# packages/policy/action_handlers.py

import requests
import tempfile

async def execute_telegram_action(...):
    snapshot_url = context.get('snapshot_path')
    
    if snapshot_url and snapshot_url.startswith('http'):
        # Download image from edge device
        response = requests.get(snapshot_url, timeout=10)
        
        if response.status_code == 200:
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                f.write(response.content)
                temp_path = f.name
            
            # Send via Telegram
            notifier.send_photo(temp_path, caption=message)
            
            # Cleanup
            os.remove(temp_path)
        else:
            logger.error(f"Failed to download image: {snapshot_url}")
    elif snapshot_url:
        # Local file path
        notifier.send_photo(snapshot_url, caption=message)
```

### Pros & Cons

✅ **Pros:**
- On-demand fetching (low bandwidth)
- Works over LAN or VPN
- No file sharing setup
- Simple implementation

❌ **Cons:**
- Edge device must run web server
- Edge must be accessible when alert triggered
- No retry if edge is down
- Security concerns (open port)

---

## Option 4: Base64 Encode in POST

Embed image data directly in the observation JSON.

### Implementation

**Edge Device:**

```python
import base64

# Encode image
_, buffer = cv2.imencode('.jpg', frame)
image_b64 = base64.b64encode(buffer).decode('utf-8')

observations = [{
    "label": "car",
    "image_data": image_b64,  # Base64-encoded JPEG
    "image_format": "jpeg"
}]
```

**Policy Server:**

```python
# Decode and save
if obs.image_data:
    image_bytes = base64.b64decode(obs.image_data)
    nparr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Save locally
    snapshot_service.save_snapshot(conn, frame, metadata)
```

### Pros & Cons

✅ **Pros:**
- No separate upload/download
- Atomic transaction
- Simple code

❌ **Cons:**
- 33% larger payloads (base64 overhead)
- High bandwidth
- Large JSON payloads
- Poor for high-res images

---

## Recommended Architecture

### **For LAN Deployment (Raspberry Pi on local network):**

**Use Option 1 (Network File Share)** or **Option 3 (HTTP Server)**

```python
# Edge Device
EDGE_IMAGE_DIR = "/var/echoBell/images"

# Save image
filename = f"cam{camera_id}_{timestamp}.jpg"
cv2.imwrite(f"{EDGE_IMAGE_DIR}/{filename}", frame)

# Send filename only (not full path)
observations = [{
    "label": "car",
    "snapshot_filename": filename  # Just the filename
}]

# Policy Server
EDGE_MOUNT = "/mnt/edge_images"  # Option 1: Network mount
# OR
EDGE_URL = "http://192.168.1.100:8080"  # Option 3: HTTP server

# Construct full path/URL
if EDGE_MOUNT:
    full_path = f"{EDGE_MOUNT}/{filename}"
elif EDGE_URL:
    full_path = f"{EDGE_URL}/{filename}"
```

### **For Remote/Cloud Deployment:**

**Use Option 2 (Upload to Central)**

Edge devices upload images to central server, which stores them permanently.

---

## Docker Compose Example

```yaml
# docker-compose.yml

services:
  policy-server:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - edge_images:/mnt/edge_images  # Shared volume
    environment:
      - EDGE_IMAGE_MOUNT=/mnt/edge_images
  
  camera-agent:
    build: ./apps/camera-agent
    volumes:
      - edge_images:/var/echoBell/images  # Same shared volume
    environment:
      - EDGE_IMAGE_DIR=/var/echoBell/images
      - POLICY_SERVER_URL=http://policy-server:8000

volumes:
  edge_images:  # Shared between services
```

With Docker volumes, both containers access the same filesystem!

---

## Security Considerations

1. **Network Share:**
   - Use read-only mounts on policy server
   - Restrict share to specific IPs
   - Consider VPN for remote access

2. **HTTP Server:**
   - Add authentication (API key in header)
   - Use HTTPS with self-signed cert
   - Firewall to policy server IP only

3. **Upload:**
   - Validate image format/size
   - Rate limit uploads
   - Use HTTPS

---

## Performance Comparison

| Approach | Image Access Time | Network Usage | Storage Cost |
|----------|------------------|---------------|--------------|
| Network Share | ~50ms (LAN) | Low (on-demand) | 1x (edge only) |
| Upload | Immediate | High (eager) | 2x (edge + central) |
| HTTP Server | ~100ms (download) | Low (on-demand) | 1x (edge only) |
| Base64 POST | Immediate | Very High | 1.33x (encoding) |

---

## Recommendation

**Start Simple:**

1. If edge and policy server are in same Docker network: **Use shared Docker volume** (simplest)
2. If edge is on LAN: **Use HTTP server** (Option 3) - easy to implement, works well
3. If edge is remote: **Use upload** (Option 2) - cleaner architecture

**Example for HTTP Server (Recommended):**

```python
# Edge device - apps/camera-agent/main.py
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

# Start image server
def serve_images():
    handler = lambda *args: SimpleHTTPRequestHandler(
        *args, directory="/var/echoBell/images"
    )
    server = HTTPServer(('0.0.0.0', 8080), handler)
    server.serve_forever()

threading.Thread(target=serve_images, daemon=True).start()

# Save images
cv2.imwrite(f"/var/echoBell/images/cam1_{ts}.jpg", frame)

# Send URL to policy server
requests.post("http://policy-server:8000/observations", json={
    "snapshot_path": f"http://edge-device:8080/cam1_{ts}.jpg"
})
```

This is **~20 lines of code** and works great for most deployments!
