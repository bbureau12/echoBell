from dataclasses import dataclass
import os
import sys
import redis

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apps.app import AppConfig


def test_redis(config: AppConfig) -> None:
    print(f"[test] connecting to redis at {config.redis_host}:{config.redis_port}")
    print(f"[test] redis_enabled: {config.redis_enabled}")

    if not config.redis_enabled:
        print("[test] redis is disabled in config")
        return

    r = redis.Redis(
        host=config.redis_host,
        port=config.redis_port,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    # 1️⃣ connectivity
    pong = r.ping()
    print("[test] ping ->", pong)

    # 2️⃣ write
    r.set("echobell:test", "ok", ex=10)
    print("[test] set echobell:test")

    # 3️⃣ read
    val = r.get("echobell:test")
    print("[test] get echobell:test ->", val)

    assert val == b"ok", "Redis round-trip failed"

    print("[test] redis OK")


if __name__ == "__main__":
    # Load config from config.json or use defaults
    config_path = os.path.join(ROOT, "config.json")
    cfg = AppConfig.from_json_or_defaults(config_path)
    test_redis(cfg)
