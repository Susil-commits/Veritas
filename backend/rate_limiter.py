"""
Rate Limiter & Cooldown Manager
Protects LLM (Gemini) and TTS (ElevenLabs) quotas from accidental multi-clicks,
rapid automated loops, and stress testing during demos.
"""
import time
import threading
from collections import defaultdict
from fastapi import HTTPException, status
from services.redis_service import redis_service

class RateLimiter:
    def __init__(self):
        # Maps key -> last timestamp of request
        self._last_request_time: dict[str, float] = {}
        # Maps key -> list of recent timestamps
        self._request_history: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _cleanup_if_needed(self, now: float) -> None:
        """Prune entries older than 1 hour when cache grows large."""
        if len(self._last_request_time) > 2000:
            threshold = now - 3600
            self._last_request_time = {k: v for k, v in self._last_request_time.items() if v > threshold}
            self._request_history = defaultdict(list, {k: v for k, v in self._request_history.items() if v and v[-1] > threshold})

    def enforce_cooldown(
        self,
        key: str,
        cooldown_seconds: float = 1.5,
        action: str = "messages",
        max_per_minute: int = 30,
    ):
        """
        Enforce both a minimum cooldown between requests and a maximum requests per minute cap.
        Throws HTTP 429 if violated.
        """
        now = time.time()
        with self._lock:
            last_time = self._last_request_time.get(key, 0.0)

            # 1. Enforce burst cooldown
            elapsed = now - last_time
            if elapsed < cooldown_seconds:
                remaining = round(cooldown_seconds - elapsed, 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Please slow down! Wait {remaining}s before sending another {action}.",
                    headers={"Retry-After": str(max(1, int(remaining)))},
                )

            # 2. Enforce sliding-window requests per minute
            history = self._request_history[key]
            one_min_ago = now - 60.0
            # prune older timestamps
            active_history = [t for t in history if t > one_min_ago]
            
            if len(active_history) >= max_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: maximum {max_per_minute} {action} per minute reached. Please pause for a moment.",
                    headers={"Retry-After": "30"},
                )

            # Check distributed Redis rate limit BEFORE committing local state.
            # If Redis rejects the request, we must NOT record it locally — otherwise
            # the local counter would be inflated, accelerating future false lockouts.
            if redis_service.is_connected and cooldown_seconds >= 1.0:
                allowed, _remaining = redis_service.check_rate_limit(
                    key=f"cooldown:{key}",
                    limit=max_per_minute,
                    window_seconds=60,
                )
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Rate limit exceeded: maximum {max_per_minute} {action} per minute reached. Please pause for a moment.",
                        headers={"Retry-After": "30"},
                    )

            # Record this request only after all checks pass
            active_history.append(now)
            self._request_history[key] = active_history
            self._last_request_time[key] = now

            self._cleanup_if_needed(now)

    def enforce_auth_rate_limit(
        self,
        key: str,
        max_attempts: int = 5,
        window_seconds: float = 60.0,
    ):
        """
        Protects session token issuance (/session/start) and authentication entrypoints
        from automated brute-force spamming, session flooding, and credential enumeration.
        Allows up to max_attempts within window_seconds. Throws HTTP 429 if exceeded.
        """
        now = time.time()
        auth_key = f"auth_{key}"
        with self._lock:
            history = self._request_history[auth_key]
            window_start = now - window_seconds
            active_attempts = [t for t in history if t > window_start]

            if len(active_attempts) >= max_attempts:
                oldest_active = active_attempts[0]
                remaining_lockout = max(1, int(window_seconds - (now - oldest_active)))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many authentication attempts. Please wait {remaining_lockout} seconds before trying again.",
                    headers={"Retry-After": str(remaining_lockout)},
                )

            # Check distributed Redis rate limit BEFORE committing local state.
            if redis_service.is_connected:
                allowed, _remaining = redis_service.check_rate_limit(
                    key=f"auth:{key}",
                    limit=max_attempts,
                    window_seconds=int(window_seconds),
                )
                if not allowed:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many authentication attempts. Please try again later.",
                        headers={"Retry-After": str(max(1, int(window_seconds)))},
                    )

            # Record attempt only after all checks pass
            active_attempts.append(now)
            self._request_history[auth_key] = active_attempts
            self._last_request_time[auth_key] = now

            self._cleanup_if_needed(now)


# Global singleton instance
limiter = RateLimiter()

