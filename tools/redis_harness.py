from dataclasses import dataclass
import os
import redis


@dataclass(frozen=True)
class RedisConfig:
    host: str = os.getenv("REDIS_HOST", "localhost")
    port: int = int(os.getenv("REDIS_PORT", "6379"))


def test_redis(config: RedisConfig) -> None:
    print(f"[test] connecting to redis at {config.host}:{config.port}")

    r = redis.Redis(
        host=config.host,
        port=config.port,
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
    cfg = RedisConfig()
    test_redis(cfg)
