"""
Redis Service for Veritas — High-Performance Distributed Caching & Session Storage.
Provides distributed session management, LLM response caching, and rate limiting with
seamless in-memory fallback when Redis is unreachable, throttled, or exceeding quota.
"""
import os
import time
import json
import threading
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv()

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class ResilientRedisService:
    def __init__(self):
        self._client: Optional[Any] = None
        self._is_connected: bool = False
        self._last_warn_time: float = 0.0
        self._memory_cache: dict[str, tuple[Any, float]] = {}
        self._memory_lock = threading.Lock()
        self._init_connection()

    def _init_connection(self):
        redis_uri = os.getenv("REDIS_URI")
        if not redis_uri or not REDIS_AVAILABLE:
            self._client = None
            self._is_connected = False
            return

        try:
            # Low timeouts ensure app NEVER hangs if Upstash is rate-limited or slow
            self._client = redis.from_url(
                redis_uri,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
                retry_on_timeout=False,
            )
            # Test ping
            self._client.ping()
            self._is_connected = True
            print("[INFO] RedisService: Connected to Upstash Redis.")
        except Exception as e:
            self._client = None
            self._is_connected = False
            print(f"[INFO] RedisService: Upstash Redis offline or quota reached ({e}). Using resilient in-memory fallback.")

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def get(self, key: str) -> Optional[str]:
        if self._is_connected and self._client:
            try:
                return self._client.get(key)
            except Exception as e:
                self._handle_redis_error(e)

        # In-memory fallback
        with self._memory_lock:
            if key in self._memory_cache:
                val, expires_at = self._memory_cache[key]
                if expires_at == 0 or expires_at > time.time():
                    return str(val)
                del self._memory_cache[key]
        return None

    def set(self, key: str, value: Any, ex: int = 86400) -> bool:
        str_val = value if isinstance(value, str) else json.dumps(value)
        if self._is_connected and self._client:
            try:
                return bool(self._client.set(key, str_val, ex=ex))
            except Exception as e:
                self._handle_redis_error(e)

        # In-memory fallback
        expires_at = time.time() + ex if ex > 0 else 0
        with self._memory_lock:
            self._memory_cache[key] = (str_val, expires_at)
        return True

    def get_json(self, key: str) -> Optional[Any]:
        raw = self.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def set_json(self, key: str, value: Any, ex: int = 86400) -> bool:
        try:
            str_val = json.dumps(value)
            return self.set(key, str_val, ex=ex)
        except Exception as e:
            print(f"[WARN] RedisService: Failed to serialize JSON for key '{key}': {e}")
            return False

    def delete(self, key: str) -> bool:
        if self._is_connected and self._client:
            try:
                self._client.delete(key)
            except Exception as e:
                self._handle_redis_error(e)

        with self._memory_lock:
            self._memory_cache.pop(key, None)
        return True

    def check_rate_limit(self, key: str, limit: int = 15, window_seconds: int = 60) -> tuple[bool, int]:
        """
        Sliding window / counter rate limiting.
        Returns: (allowed: bool, remaining: int)
        """
        r_key = f"veritas:ratelimit:{key}"
        if self._is_connected and self._client:
            try:
                current = self._client.incr(r_key)
                if current == 1:
                    self._client.expire(r_key, window_seconds)
                remaining = max(0, limit - current)
                return (current <= limit, remaining)
            except Exception as e:
                self._handle_redis_error(e)

        # In-memory fallback
        with self._memory_lock:
            now = time.time()
            if r_key in self._memory_cache:
                count, expires_at = self._memory_cache[r_key]
                if now < expires_at:
                    count = int(count) + 1
                    self._memory_cache[r_key] = (count, expires_at)
                    remaining = max(0, limit - count)
                    return (count <= limit, remaining)
            self._memory_cache[r_key] = (1, now + window_seconds)
            return (True, limit - 1)

    def _handle_redis_error(self, e: Exception):
        now = time.time()
        # Warn at most once every 60 seconds to prevent log flooding
        if now - self._last_warn_time > 60:
            print(f"[WARN] RedisService transient error ({e}); seamlessly continuing with memory fallback.")
            self._last_warn_time = now
        # If it was a quota or auth error, flag as disconnected so operations don't keep hammering
        err_msg = str(e).lower()
        if "quota" in err_msg or "limit exceeded" in err_msg or "authentication" in err_msg:
            self._is_connected = False


# Singleton instance
redis_service = ResilientRedisService()
