from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from typing import Optional, Dict
import sqlite3

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from packages.common.types import Camera, CameraCapabilities
from packages.data.cache.cache import Cache


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

    def __init__(self, conn: sqlite3.Connection, cache: Optional[Cache] = None, cache_ttl_s: int = 86400):
        """
        Args:
            conn: Database connection
            cache: Optional cache instance
            cache_ttl_s: Cache TTL in seconds (default: 86400 = 24 hours)
        """
        self.conn = conn
        self.cache = cache
        self.cache_ttl_s = cache_ttl_s

    def _camera_from_row(self, row: tuple) -> Camera:
        """Convert a database row to a Camera object."""
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

    def _serialize_camera(self, camera: Camera) -> str:
        """Serialize a Camera object to JSON for caching."""
        return json.dumps({
            "id": camera.id,
            "name": camera.name,
            "location_id": camera.location_id,
            "description": camera.description,
            "capability_level_id": camera.capability_level_id,
            "hostname": camera.hostname,
            "ip_address": camera.ip_address,
            "port": camera.port,
            "protocol": camera.protocol,
            "endpoint": camera.endpoint,
            "stream_url": camera.stream_url,
            "auth_profile_id": camera.auth_profile_id,
        })

    def _deserialize_camera(self, data: str) -> Camera:
        """Deserialize a Camera object from JSON cache."""
        d = json.loads(data)
        return Camera(
            id=d["id"],
            name=d["name"],
            location_id=d["location_id"],
            description=d["description"],
            capability_level_id=d["capability_level_id"],
            capability=capabilities_from_level(d["capability_level_id"]),
            hostname=d["hostname"],
            ip_address=d["ip_address"],
            port=d["port"],
            protocol=d["protocol"],
            endpoint=d["endpoint"],
            stream_url=d["stream_url"],
            auth_profile_id=d["auth_profile_id"],
        )

    def get_by_id(self, camera_id: int) -> Optional[Camera]:
        # Try cache first
        if self.cache:
            cache_key = f"camera:{camera_id}"
            cached = self.cache.get(cache_key)
            if cached:
                return self._deserialize_camera(cached)

        # Cache miss - query database
        # Try with auth_profile_id first, fallback if column doesn't exist
        try:
            row = self.conn.execute(
                """
                SELECT id, name, location_id, description, capability_level_id,
                       hostname, ip_address, port, protocol, endpoint, stream_url, auth_profile_id
                FROM camera
                WHERE id = ?
                """,
                (camera_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            # Fallback for databases without auth_profile_id column
            row = self.conn.execute(
                """
                SELECT id, name, location_id, description, capability_level_id,
                       hostname, ip_address, port, protocol, endpoint, stream_url, NULL as auth_profile_id
                FROM camera
                WHERE id = ?
                """,
                (camera_id,),
            ).fetchone()

        if not row:
            return None

        camera = self._camera_from_row(row)

        # Store in cache
        if self.cache:
            self.cache.set(cache_key, self._serialize_camera(camera), ttl_s=self.cache_ttl_s)

        return camera

    def list_all(self) -> list[Camera]:
        # Try cache first
        if self.cache:
            cache_key = "camera:list_all"
            cached = self.cache.get(cache_key)
            if cached:
                data = json.loads(cached)
                return [self._deserialize_camera(json.dumps(cam_dict)) for cam_dict in data]

        # Cache miss - query database
        # Try with auth_profile_id first, fallback if column doesn't exist
        try:
            rows = self.conn.execute(
                """
                SELECT id, name, location_id, description, capability_level_id,
                       hostname, ip_address, port, protocol, endpoint, stream_url, auth_profile_id
                FROM camera
                ORDER BY id
                """
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback for databases without auth_profile_id column
            rows = self.conn.execute(
                """
                SELECT id, name, location_id, description, capability_level_id,
                       hostname, ip_address, port, protocol, endpoint, stream_url, NULL as auth_profile_id
                FROM camera
                ORDER BY id
                """
            ).fetchall()

        cams: list[Camera] = [self._camera_from_row(row) for row in rows]

        # Store in cache
        if self.cache:
            serialized_list = json.dumps([json.loads(self._serialize_camera(cam)) for cam in cams])
            self.cache.set(cache_key, serialized_list, ttl_s=self.cache_ttl_s)

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
    cache: Optional[Cache] = None
    cache_ttl_s: int = 86400  # 24 hours default

    def get_camera(self, conn: sqlite3.Connection, camera_id: int) -> Optional[Camera]:
        if self.registry:
            cam = self.registry.get_by_id(camera_id)
            if cam:
                return cam
        return CameraRepository(conn, cache=self.cache, cache_ttl_s=self.cache_ttl_s).get_by_id(camera_id)
