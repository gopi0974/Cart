import time
from typing import Any, Optional, Dict, Tuple
from threading import Lock


class SimpleTTLCache:
    """Thread-safe in-memory cache with time-to-live (TTL) expiration for static catalog and health data."""
    def __init__(self, ttl_seconds: int = 45):
        self.default_ttl = ttl_seconds
        self._cache: Dict[str, Tuple[float, float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            if key in self._cache:
                created_at, ttl, value = self._cache[key]
                if now - created_at < ttl:
                    return value
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        now = time.time()
        valid_ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._cache[key] = (now, valid_ttl, value)

    def invalidate(self, prefix: Optional[str] = None):
        with self._lock:
            if prefix is None:
                self._cache.clear()
            else:
                for k in list(self._cache.keys()):
                    if k.startswith(prefix):
                        del self._cache[k]

    def clear(self):
        self.invalidate()


catalog_cache = SimpleTTLCache(ttl_seconds=45)

