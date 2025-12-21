from __future__ import annotations
from typing import Optional, Protocol

class MemoryCache:
    def __init__(self):
        self._d: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._d.get(key)

    def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        self._d[key] = value

    def delete(self, key: str) -> None:
        self._d.pop(key, None)

class Cache(Protocol):
    def get(self, key: str) -> Optional[str]: ...
    def set(self, key: str, value: str, ttl_s: int | None = None) -> None: ...
    def delete(self, key: str) -> None: ...

import redis
from typing import Optional

class RedisCache:
    def __init__(self, client: redis.Redis):
        self.client = client

    def get(self, key: str) -> Optional[str]:
        v = self.client.get(key)
        return v.decode("utf-8") if v else None

    def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        if ttl_s:
            self.client.setex(key, ttl_s, value)
        else:
            self.client.set(key, value)

    def delete(self, key: str) -> None:
        self.client.delete(key)
