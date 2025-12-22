from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from typing import Optional, Dict
import sqlite3

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from packages.common.types import Camera, CameraCapabilities


def capabilities_from_level(level_id: int) -> CameraCapabilities:
    """
    Maps capability level id to boolean capability flags.

    1 = Landscape (broad motion tracking)
    2 = Vehicle detail
    3 = Facial detail
    """
    return CameraCapabilities(
        allow_landscape=True,
        allow_vehicle_detail=level_id >= 2,
        allow_facial_detail=level_id >= 3,
    )


class CameraRepository:
    """
    DB-facing camera data access (read/write).
    Keep this mostly SQL + mapping, minimal business logic.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_by_id(self, camera_id: int) -> Optional[Camera]:
        row = self.conn.execute(
            """
            SELECT id, name, location_id, description, capability_level_id,
                   hostname, ip_address, port, protocol, endpoint, stream_url, auth_profile_id
            FROM camera
            WHERE id = ?
            """,
            (camera_id,),
        ).fetchone()

        if not row:
            return None

        (cam_id, name, location_id, description, level_id,
         hostname, ip_address, port, protocol, endpoint, stream_url, auth_profile_id) = row
        level_id = int(level_id)

        return Camera(
            id=int(cam_id),
            name=str(name),
            location_id=location_id if location_id is None else int(location_id),
            description=description,
            capability_level_id=level_id,
            capability=capabilities_from_level(level_id),
            hostname=hostname,
            ip_address=ip_address,
            port=port if port is None else int(port),
            protocol=protocol,
            endpoint=endpoint,
            stream_url=stream_url,
            auth_profile_id=auth_profile_id if auth_profile_id is None else int(auth_profile_id),
        )

    def list_all(self) -> list[Camera]:
        rows = self.conn.execute(
            """
            SELECT id, name, location_id, description, capability_level_id,
                   hostname, ip_address, port, protocol, endpoint, stream_url, auth_profile_id
            FROM camera
            ORDER BY id
            """
        ).fetchall()

        cams: list[Camera] = []
        for (cam_id, name, location_id, description, level_id,
             hostname, ip_address, port, protocol, endpoint, stream_url, auth_profile_id) in rows:
            level_id = int(level_id)
            cams.append(
                Camera(
                    id=int(cam_id),
                    name=str(name),
                    location_id=location_id if location_id is None else int(location_id),
                    description=description,
                    capability_level_id=level_id,
                    capability=capabilities_from_level(level_id),
                    hostname=hostname,
                    ip_address=ip_address,
                    port=port if port is None else int(port),
                    protocol=protocol,
                    endpoint=endpoint,
                    stream_url=stream_url,
                    auth_profile_id=auth_profile_id if auth_profile_id is None else int(auth_profile_id),
                )
            )
        return cams


class CameraRegistry:
    """
    In-memory camera lookup (useful for tests, harnesses, and offline runs).
    """

    def __init__(self, cameras: Dict[int, Camera] | None = None):
        self._cams: Dict[int, Camera] = dict(cameras or {})

    def get_by_id(self, camera_id: int) -> Optional[Camera]:
        return self._cams.get(camera_id)

    def add(self, camera: Camera) -> None:
        self._cams[camera.id] = camera


@dataclass(frozen=True)
class CameraService:
    """
    Facade that can read cameras from either:
    - in-memory registry (tests)
    - DB repository (production)
    """

    registry: Optional[CameraRegistry] = None

    def get_camera(self, conn: sqlite3.Connection, camera_id: int) -> Optional[Camera]:
        if self.registry:
            cam = self.registry.get_by_id(camera_id)
            if cam:
                return cam
        return CameraRepository(conn).get_by_id(camera_id)
