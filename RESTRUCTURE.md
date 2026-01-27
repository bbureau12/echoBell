# EchoBell Restructuring Complete

The project has been reorganized for clarity:

## Old Structure
```
apps/
├── camera-agent/       # Passive camera
├── doorbell-agent/     # Interactive doorbell
├── orchestrator/       # Test code (mixed)
├── scheduler-daemon/   # Central scheduler
└── policy-server/      # Central policy engine
```

## New Structure
```
edge/
└── agent/              # Unified edge agent (camera or doorbell)
    ├── main.py         # Config-driven entry point
    ├── camera_loop.py  # Passive monitoring
    ├── button_loop.py  # Interactive doorbell
    ├── image_server.py # HTTP server
    └── config.yaml     # Device configuration

central/
├── policy-server/      # Policy engine (FastAPI)
└── scheduler/          # Camera scheduler

packages/               # Shared library code
└── scene/
    └── behavior_manager.py  # Moved from apps/orchestrator/
```

## Benefits

✅ **Clear separation**: Edge devices vs Central services  
✅ **Single codebase**: One agent for cameras and doorbells  
✅ **Config-driven**: Same code, different behavior via config.yaml  
✅ **No duplication**: Shared code properly in packages/  

## Migration Notes

- `apps/camera-agent/` → `edge/agent/` (camera_loop.py)
- `apps/doorbell-agent/` → `edge/agent/` (button_loop.py)
- `apps/orchestrator/` → Deleted (test code)
- `apps/scheduler-daemon/` → `central/scheduler/`
- `apps/policy-server/` → `central/policy-server/`

## Running Tests

All tests should still pass:

```bash
python tests/run_all_tests.py
```
