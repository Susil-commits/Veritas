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
    redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


class ResilientRedisService:
    def __init__(self):
        self._client: Optional[Any] = None
        self._is_connected: bool = False
        self._last_warn_time: float = 0.0
        self._circuit_open_until: float = 0.0
        self._consecutive_errors: int = 0
        self._memory_cache: dict[str, tuple[Any, float]] = {}
        self._memory_lock = threading.Lock()
        self._init_connection()

    def _init_connection(self):
        # In test mode, use the ultra-fast thread-safe memory store to avoid network overhead
        if os.getenv("VERITAS_TEST_MODE", "false").lower() == "true":
            self._client = None
            self._is_connected = False
            return

        redis_uri = os.getenv("REDIS_URI") or os.getenv("REDIS_URL") or os.getenv("UPSTASH_REDIS_URL")
        if not redis_uri or not REDIS_AVAILABLE or redis is None:
            self._client = None
            self._is_connected = False
            return

        try:
            # Low timeouts (0.5s) ensure app NEVER hangs if Upstash is rate-limited or lagging
            self._client = redis.from_url(
                redis_uri,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                retry_on_timeout=False,
            )
            # Test ping
            if self._client is not None:
                self._client.ping()
                self._is_connected = True
                self._consecutive_errors = 0
                self._circuit_open_until = 0.0
                print("[INFO] RedisService: Connected to Upstash Redis.")
            else:
                self._is_connected = False
        except Exception as e:
            self._client = None
            self._is_connected = False
            self._circuit_open_until = time.time() + 60.0
            print(f"[INFO] RedisService: Upstash Redis offline or quota reached ({e}). Using resilient in-memory fallback.")

    @property
    def is_connected(self) -> bool:
        if not self._is_connected or not self._client:
            return False
        now = time.time()
        # If circuit breaker is tripped, stay in memory without blocking network calls
        if now < self._circuit_open_until:
            return False
        return True

    def get(self, key: str) -> Optional[str]:
        if self.is_connected and self._client:
            try:
                res = self._client.get(key)
                self._consecutive_errors = 0
                return res
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
        if self.is_connected and self._client:
            try:
                res = bool(self._client.set(key, str_val, ex=ex))
                self._consecutive_errors = 0
                return res
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
        if self.is_connected and self._client:
            try:
                self._client.delete(key)
                self._consecutive_errors = 0
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
        if self.is_connected and self._client:
            try:
                current = self._client.incr(r_key)
                if current == 1:
                    self._client.expire(r_key, window_seconds)
                self._consecutive_errors = 0
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
        self._consecutive_errors += 1
        err_msg = str(e).lower()

        # Check if error indicates timeout, connection failure, quota limit, or unreachable host
        is_break_condition = (
            any(kw in err_msg for kw in [
                "timeout", "timed out", "quota", "limit exceeded", "authentication",
                "connection", "refused", "reset", "unreachable", "down"
            ])
            or self._consecutive_errors >= 2
        )

        if is_break_condition:
            self._circuit_open_until = now + 45.0  # Open circuit for 45s
            self._is_connected = False
            if now - self._last_warn_time > 30:
                print(f"[WARN] RedisService circuit breaker tripped ({e}); seamlessly routing to in-memory fallback for 45s.")
                self._last_warn_time = now
        else:
            if now - self._last_warn_time > 60:
                print(f"[WARN] RedisService transient error ({e}); seamlessly continuing with memory fallback.")
                self._last_warn_time = now


# Singleton instance
redis_service = ResilientRedisService()
