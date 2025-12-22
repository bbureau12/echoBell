import json, os, sys
from typing import Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from packages.common.types import Camera, CameraCapabilities

def camera_to_json(cam: Camera) -> str:
    payload = {
        "id": cam.id,
        "name": cam.name,
        "location_id": cam.location_id,
        "description": cam.description,
        "capability_level_id": cam.capability_level_id,
        "capabilities": {
            "allow_landscape": cam.capabilities.allow_landscape,
            "allow_vehicle_detail": cam.capabilities.allow_vehicle_detail,
            "allow_facial_detail": cam.capabilities.allow_facial_detail,
        },
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

def camera_from_json(s: str) -> Camera:
    data: dict[str, Any] = json.loads(s)
    caps = data.get("capabilities") or {}
    return Camera(
        id=int(data["id"]),
        name=str(data["name"]),
        location_id=data.get("location_id"),
        description=data.get("description"),
        capability_level_id=int(data["capability_level_id"]),
        capabilities=CameraCapabilities(
            allow_landscape=bool(caps.get("allow_landscape", True)),
            allow_vehicle_detail=bool(caps.get("allow_vehicle_detail", False)),
            allow_facial_detail=bool(caps.get("allow_facial_detail", False)),
        ),
    )
