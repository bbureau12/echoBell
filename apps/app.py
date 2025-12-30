from dataclasses import dataclass
import sys
from typing import Optional
import os
import redis
import json
import secrets

from packages.data.camera_service import CameraService
from packages.perception.plate_service import PlateService
from packages.perception.plate_heurystics import PlateModifiers
from packages.common.config_models import RetentionSettings

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
    plate_secret_key: Optional[str] = None  # Hex string for plate hashing
    retention: RetentionSettings = None
    plate_modifiers: PlateModifiers = None

    def __post_init__(self):
        # Ensure retention is set to defaults if None
        if self.retention is None:
            object.__setattr__(self, 'retention', RetentionSettings())
        # Ensure plate_modifiers is set to defaults if None
        if self.plate_modifiers is None:
            object.__setattr__(self, 'plate_modifiers', PlateModifiers())

    @classmethod
    def from_json(cls, json_path: str) -> "AppConfig":
        """Load configuration from a JSON file."""
        with open(json_path, "r") as f:
            data = json.load(f)
        
        # Handle retention settings separately
        retention_data = data.pop("retention", {})
        retention = RetentionSettings(**retention_data) if retention_data else RetentionSettings()
        
        # Handle plate_modifiers settings separately
        plate_modifiers_data = data.pop("plate_modifiers", {})
        plate_modifiers = PlateModifiers(**plate_modifiers_data) if plate_modifiers_data else PlateModifiers()
        
        return cls(**data, retention=retention, plate_modifiers=plate_modifiers)

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
            cache_long_minutes=1440,
            retention=RetentionSettings()
        )

@dataclass
class AppContext:
    config: AppConfig
    cache: Optional[Cache]
    camera_service: Optional[CameraService]
    plate_service: Optional[PlateService]

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
        cache_ttl_s=config.cache_long_minutes * 60, # 24 hours default
    )

    # Initialize PlateService with secret key
    plate_secret_key = None
    if config.plate_secret_key:
        # Use provided hex string
        plate_secret_key = bytes.fromhex(config.plate_secret_key)
    else:
        # Generate a random 32-byte key (for development/testing)
        # In production, this should be stored in config
        plate_secret_key = secrets.token_bytes(32)
    
    plate_service = PlateService(secret_key=plate_secret_key)

    return AppContext(
        config=config, 
        cache=cache, 
        camera_service=camera_service,
        plate_service=plate_service
    )