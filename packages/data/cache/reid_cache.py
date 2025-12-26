from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import json
import time

from packages.data.cache.cache import Cache

@dataclass(frozen=True)
class ReidHit:
    """
    Represents a cached ReID (Re-Identification) match result.
    This stores information about a visitor match, NOT a camera object.
    """
    visitor_id: str
    sim: float
    ts: int
    camera_id: int  # Which camera saw this visitor (metadata only)
    model_name: str
    trusted_pending: bool = False
    trusted_verified: bool = False

def _cam_key(camera_id: int) -> str:
    """Cache key for the most recent ReID hit on a specific camera."""
    return f"reid:cam:{camera_id}:best"

def _visitor_key(visitor_id: str) -> str:
    """Cache key for the last time a specific visitor was seen."""
    return f"reid:visitor:{visitor_id}:last_seen"

def get_cached_cam_hit(cache: Optional[Cache], *, camera_id: int, model_name: str, max_age_s: int = 120) -> Optional[ReidHit]:
    """
    Get the most recent visitor ReID match for a specific camera.
    
    This retrieves the LAST VISITOR MATCH seen on this camera, not the camera object itself.
    Use CameraService.get_camera() if you need the actual camera configuration.
    
    Args:
        cache: Cache instance (if None, returns None)
        camera_id: ID of the camera to check (used as cache key, not loaded from DB)
        model_name: ReID model name to match
        max_age_s: Maximum age of cached hit in seconds (default 120s)
    
    Returns:
        ReidHit if found and valid, None otherwise
    """
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
    """
    Store the most recent visitor ReID match for a specific camera.
    
    This caches which visitor was last seen on this camera for quick lookups.
    Does NOT store camera configuration - use CameraService for that.
    
    Args:
        cache: Cache instance (if None, no-op)
        hit: The ReID match result to cache
        ttl_s: Time-to-live in seconds (default 120s)
    """
    if not cache:
        return
    cache.set(
        _cam_key(hit.camera_id),
        json.dumps(hit.__dict__, separators=(",", ":"), ensure_ascii=False),
        ttl_s=ttl_s,
    )

def set_cached_last_seen(cache: Optional[Cache], hit: ReidHit, *, ttl_s: int = 300) -> None:
    """
    Store when and where a specific visitor was last seen.
    
    This caches visitor sighting information for quick "have we seen this person recently?" checks.
    
    Args:
        cache: Cache instance (if None, no-op)
        hit: The ReID match result containing visitor_id and timing
        ttl_s: Time-to-live in seconds (default 300s)
    """
    if not cache:
        return
    cache.set(
        _visitor_key(hit.visitor_id),
        json.dumps(hit.__dict__, separators=(",", ":"), ensure_ascii=False),
        ttl_s=ttl_s,
    )

def get_cached_last_seen(cache: Optional[Cache], *, visitor_id: str, model_name: str, max_age_s: int = 300) -> Optional[ReidHit]:
    """
    Get when and where a specific visitor was last seen.
    
    This retrieves the most recent sighting information for a known visitor.
    Useful for determining if we've seen this person recently.
    
    Args:
        cache: Cache instance (if None, returns None)
        visitor_id: ID of the visitor to check
        model_name: ReID model name to match
        max_age_s: Maximum age of cached hit in seconds (default 300s)
    
    Returns:
        ReidHit if found and valid, None otherwise
    """
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
