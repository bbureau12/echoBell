from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import json
import time

from packages.data.cache.cache import Cache

@dataclass(frozen=True)
class ReidHit:
    visitor_id: str
    sim: float
    ts: int
    camera_id: int
    model_name: str
    trusted_pending: bool = False
    trusted_verified: bool = False

def _cam_key(camera_id: int) -> str:
    return f"reid:cam:{camera_id}:best"

def _visitor_key(visitor_id: str) -> str:
    return f"reid:visitor:{visitor_id}:last_seen"

def get_cached_cam_hit(cache: Optional[Cache], *, camera_id: int, model_name: str, max_age_s: int = 120) -> Optional[ReidHit]:
    if not cache:
        return None
    raw = cache.get(_cam_key(camera_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data.get("model_name") != model_name:
            return None
        ts = int(data.get("ts", 0))
        now = int(time.time())
        if now - ts > max_age_s:
            return None
        return ReidHit(
            visitor_id=str(data["visitor_id"]),
            sim=float(data["sim"]),
            ts=ts,
            camera_id=int(data["camera_id"]),
            model_name=str(data["model_name"]),
        )
    except Exception:
        # Corrupt payload; clear it
        cache.delete(_cam_key(camera_id))
        return None

def set_cached_cam_hit(cache: Optional[Cache], hit: ReidHit, *, ttl_s: int = 120) -> None:
    if not cache:
        return
    cache.set(
        _cam_key(hit.camera_id),
        json.dumps(hit.__dict__, separators=(",", ":"), ensure_ascii=False),
        ttl_s=ttl_s,
    )

def set_cached_last_seen(cache: Optional[Cache], hit: ReidHit, *, ttl_s: int = 300) -> None:
    if not cache:
        return
    cache.set(
        _visitor_key(hit.visitor_id),
        json.dumps(hit.__dict__, separators=(",", ":"), ensure_ascii=False),
        ttl_s=ttl_s,
    )

def get_cached_last_seen(cache: Optional[Cache], *, visitor_id: str, model_name: str, max_age_s: int = 300) -> Optional[ReidHit]:
    print("get_cached_last_seen called")
    if not cache:
        print("no cache")
        return None
    raw = cache.get(_visitor_key(visitor_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data.get("model_name") != model_name:
            return None
        ts = int(data.get("ts", 0))
        now = int(time.time())
        if now - ts > max_age_s:
            return None
        return ReidHit(
            visitor_id=str(data["visitor_id"]),
            sim=float(data["sim"]),
            ts=ts,
            camera_id=int(data["camera_id"]),
            model_name=str(data["model_name"]),
        )
        print("cache pulled")
    except Exception:
        cache.delete(_visitor_key(visitor_id))
        return None
