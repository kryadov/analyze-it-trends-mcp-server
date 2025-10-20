import asyncio
import glob
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None  # type: ignore


class CacheManager:
    def __init__(self, config: dict, default_dir: Optional[str] = None) -> None:
        self.enabled: bool = bool(config.get("enabled", True))
        self.ttl_default: int = int(config.get("ttl", 3600))
        self.storage: str = str(config.get("storage", "file")).lower()
        self.redis_url: Optional[str] = config.get("redis_url") or os.getenv("REDIS_URL")
        self.dir = Path(default_dir or ".cache")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._redis = None
        if self.storage == "redis" and redis is not None and self.redis_url:
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    def _file_path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(":", "_")
        return self.dir / f"{safe}.json"

    def get(self, key: str) -> Any:
        if not self.enabled:
            return None
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is None:
                    return None
                obj = json.loads(raw)
                if obj.get("expires_at") and obj["expires_at"] < time.time():
                    return None
                return obj.get("value")
            except Exception:  # pragma: no cover
                return None
        # file-based
        path = self._file_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.get("expires_at") and data["expires_at"] < time.time():
                return None
            return data.get("value")
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if not self.enabled:
            return
        ttl_use = int(ttl or self.ttl_default)
        expires_at = int(time.time() + ttl_use)
        payload = {"value": value, "expires_at": expires_at}
        if self._redis is not None:
            try:
                self._redis.set(key, json.dumps(payload), ex=ttl_use)
                return
            except Exception:  # pragma: no cover
                pass
        path = self._file_path(key)
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

    def invalidate(self, pattern: str) -> int:
        """Invalidate keys matching pattern. Returns number of invalidated entries."""
        count = 0
        if self._redis is not None:
            try:
                # Use scan to avoid blocking
                cursor = 0
                while True:
                    cursor, keys = self._redis.scan(cursor=cursor, match=pattern, count=1000)
                    if keys:
                        self._redis.delete(*keys)
                        count += len(keys)
                    if cursor == 0:
                        break
            except Exception:  # pragma: no cover
                pass
        # file-based
        for file in glob.glob(str(self.dir / f"{pattern.replace('*', '*')}.json")):
            try:
                os.remove(file)
                count += 1
            except Exception:
                pass
        return count

    def get_or_fetch(self, key: str, fetch_func: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = fetch_func()
        self.set(key, value, ttl=ttl)
        return value

    async def get_or_fetch_async(self, key: str, fetch_coro: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await fetch_coro()
        self.set(key, value, ttl=ttl)
        return value
