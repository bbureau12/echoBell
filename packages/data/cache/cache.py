from __future__ import annotations
from time import time
from typing import Optional, Protocol

class MemoryCache:
    def __init__(self):
        self._d: dict[str, tuple[str, Optional[int]]] = {}  # value, expires_at_ts

    def get(self, key: str) -> Optional[str]:
        item = self._d.get(key)
        if not item:
            return None
        value, exp = item
        if exp is not None and int(time.time()) >= exp:
            self._d.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        exp = int(time.time()) + int(ttl_s) if ttl_s else None
        self._d[key] = (value, exp)

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
