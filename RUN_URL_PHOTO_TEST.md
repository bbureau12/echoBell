# Quick Start: URL Photo Download Test

Run these commands in **3 separate PowerShell windows**.

## PowerShell Window 1: Edge Image Server

```powershell
cd D:\Projects\echoBell\echoBell
python tests\test_edge_image_server.py --create-test-image
```

**Keep this running!** You should see:
```
Server starting...
Access images at: http://localhost:8080/
```

---

## PowerShell Window 2: Policy API Server

```powershell
cd D:\Projects\echoBell\echoBell
python update_policy_photo.py
cd central\policy-server
python server.py
```

**Keep this running!** You should see:
```
Uvicorn running on http://0.0.0.0:8000
```

---

## PowerShell Window 3: Run Test

**Wait for both servers to start**, then run:

```powershell
cd D:\Projects\echoBell\echoBell
python tests\test_url_photo_download.py
```

You should see:
```
Testing URL Photo Download
[Step 1] Checking policy API server...
   [OK] Policy API server is running
[Step 2] Checking edge image server...
   [OK] Edge server is serving: http://localhost:8080/test_image.jpg
[Step 3] Sending test evidence with snapshot_url...
   [OK] Request successful!
[Step 5] Checking if image was downloaded...
   [OK] Downloaded image exists: data\downloaded_images\test_image.jpg
```

---

## Check Results

1. **Check Window 2 (Policy Server) logs** - look for:
   ```
   [TELEGRAM] Downloading image from URL: http://localhost:8080/test_image.jpg
   [TELEGRAM] Downloaded to: data/downloaded_images/test_image.jpg
   [TELEGRAM] ✓ Photo sent successfully
   ```

2. **Check Telegram** - you should receive:
   - Message: "🚗 Vehicle detected on Camera 1: white car"
   - Photo attached

3. **Check downloaded image**:
   ```powershell
   ls data\downloaded_images\
   ```

---

## Cleanup

After testing:

```powershell
# Stop servers (Ctrl+C in Windows 1 and 2)

# Clean up downloaded images
python tools\cleanup_downloaded_images.py --dry-run
python tools\cleanup_downloaded_images.py --force
```

---

## Troubleshooting

**Test says server not running?**
- Make sure Window 2 shows "Uvicorn running on http://0.0.0.0:8000"
- Wait a few seconds after starting before running test

**Edge server not found?**
- Make sure Window 1 is running
- Test manually: Open browser to http://localhost:8080/test_image.jpg

**No photo in Telegram?**
- Check Window 2 logs for errors
- Verify Telegram config: check `config.json` has valid bot_token and chat_id
