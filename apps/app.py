from dataclasses import dataclass
import sys
from typing import Optional
import os
import redis

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
            cache = None

    return AppContext(config=config, cache=cache)
