from dataclasses import dataclass
import sys
from typing import Optional
import os
import redis
import json

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
            redis_enabled=True
        )

@dataclass
class AppContext:
    config: AppConfig
    cache: Optional[Cache]

def build_context(config: AppConfig) -> AppContext:
    cache: Optional[Cache] = None

    if config.redis_enabled:
        try:
            client = redis.Redis(host=config.redis_host, port=config.redis_port, socket_connect_timeout=1)
            client.ping()
            cache = RedisCache(client)
        except Exception:
            # Cache is optional; fall back cleanly
            print(f"[redis] unavailable: {e}")
            cache = None

    return AppContext(config=config, cache=cache)
