# EchoBell Edge Agent

Unified edge agent that can operate as a passive camera or interactive doorbell.

## Quick Start

```bash
# Passive camera mode
python edge/agent/main.py --camera-id 1 --rtsp rtsp://camera:554/stream

# Interactive doorbell mode (edit config.yaml: has_button: true)
python edge/agent/main.py --camera-id 2
```

## Configuration

Edit `config.yaml` to configure:

- **Camera/Doorbell mode**: Set `has_button: true` for doorbell
- **Device capabilities**: `has_speaker`, `has_microphone`
- **Image server**: Port, directory, auto-cleanup
- **Policy server**: URL and timeout

## Architecture

```
┌─────────────────────────────────────────┐
│  Edge Agent (Raspberry Pi/NVR)         │
│                                         │
│  ┌─────────────┐  ┌─────────────┐     │
│  │ Camera Loop │  │ Button Loop │     │
│  │ (passive)   │  │ (doorbell)  │     │
│  └──────┬──────┘  └──────┬──────┘     │
│         │                 │             │
│         └────────┬────────┘             │
│                  │                      │
│         ┌────────▼────────┐            │
│         │  Event Queue    │            │
│         └────────┬────────┘            │
│                  │                      │
│         ┌────────▼────────┐            │
│         │ Policy API      │            │
│         │ Client          │            │
│         └────────┬────────┘            │
│                  │                      │
│  ┌───────────────▼──────────────┐     │
│  │ HTTP Image Server (port 8080)│     │
│  └──────────────────────────────┘     │
└──────────────┬──────────────────────────┘
               │
               │ HTTP POST
               ▼
┌──────────────────────────────────────────┐
│  Central Policy Server                   │
└──────────────────────────────────────────┘
```

## Files

- `main.py` - Unified entry point
- `camera_loop.py` - Passive monitoring
- `button_loop.py` - Interactive doorbell
- `image_server.py` - HTTP server for images
- `config.yaml` - Configuration

## See Also

- `docs/EDGE_IMAGE_SERVING.md` - Image serving architecture
- `central/policy-server/` - Policy server
