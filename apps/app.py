from dataclasses import dataclass
import sys
from typing import Optional
import os
import redis
import json

from packages.data.camera_service import CameraService

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from packages.data.cache.cache import Cache, RedisCache, MemoryCache

@dataclass(frozen=True)
class AppConfig:
    db_path: str
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_enabled: bool = True
    cache_short_minutes: int = 5
    cache_medium_minutes: int = 90
    cache_long_minutes: int = 1440

    @classmethod
    def from_json(cls, json_path: str) -> "AppConfig":
        """Load configuration from a JSON file."""
        with open(json_path, "r") as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_json_or_defaults(cls, json_path: Optional[str] = None) -> "AppConfig":
        """
        Load configuration from JSON if path is provided and exists,
        otherwise use default values.
        """
        if json_path and os.path.exists(json_path):
            return cls.from_json(json_path)
        
        # Default fallback
        return cls(
            db_path="data/doorbell.db",
            redis_host="localhost",
            redis_port=6379,
            redis_enabled=True,
            cache_short_minutes=5,
            cache_medium_minutes=90,
            cache_long_minutes=1440
        )

@dataclass
class AppContext:
    config: AppConfig
    cache: Optional[Cache]
    camera_service: Optional[CameraService]

def build_context(config: AppConfig) -> AppContext:
    cache: Optional[Cache] = None

    if config.redis_enabled:
        try:
            client = redis.Redis(
                host=config.redis_host,
                port=config.redis_port,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            cache = RedisCache(client)
            print(f"[redis] connected {config.redis_host}:{config.redis_port}")
        except Exception as e:
            print(f"[redis] unavailable: {e}")
            cache = None
    
    camera_service = CameraService(
        cache=cache,
        registry=None,     # or TEST_REGISTRY for harnesses
        ttl_s=config.cache_medium_minutes * 60, # 2 hours
    )


    return AppContext(config=config, cache=cache, camera_service=camera_service)