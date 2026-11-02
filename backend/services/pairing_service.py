"""
Pairing Service — Secure Parent-Child Account Pairing and Student Consent Verification.
Implements:
1. Server-issued 8-character pairing codes with 15-minute TTL (stored hashed with SHA-256).
2. Constant-time code validation and one-time consumption.
3. Dual-storage persistence (distributed Redis with thread-safe in-memory fallback).
"""
import hashlib
import hmac
import secrets
import threading
import time
from typing import Dict, Any, Optional

_PAIRING_STORE: Dict[str, Dict[str, Any]] = {}
_PAIRING_LOCK = threading.Lock()
PAIRING_CODE_TTL_SECONDS = 900  # 15 minutes
PAIRING_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_pairing_code(student_id: str, ttl_seconds: int = PAIRING_CODE_TTL_SECONDS) -> dict:
    """
    Generates a cryptographically random 8-character pairing code for an authenticated student.
    Stores only the SHA-256 hash with an expiration timestamp.
    """
    if not student_id:
        raise ValueError("student_id is required to issue a pairing code")

    code = "".join(secrets.choice(PAIRING_CHARS) for _ in range(8))
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    expires_at = time.time() + ttl_seconds

    # 1. Thread-safe in-memory store
    with _PAIRING_LOCK:
        _PAIRING_STORE[student_id] = {
            "hash": code_hash,
            "expires_at": expires_at,
        }

    # 2. Distributed Redis cache if available
    try:
        from services.redis_service import redis_service
        if redis_service.is_connected:
            redis_service.set_json(
                f"veritas:pairing:{student_id}",
                {"hash": code_hash, "expires_at": expires_at},
                ex=ttl_seconds,
            )
    except Exception:
        pass

    return {
        "pairing_code": code,
        "expires_in": ttl_seconds,
        "expires_at": int(expires_at),
    }


def verify_and_consume_pairing_code(student_id: str, candidate_code: Optional[str]) -> bool:
    """
    Validates a parent-submitted pairing code against the stored hash for the designated student.
    Returns True and immediately invalidates the code upon successful match.
    Fails closed (returns False) on mismatch, expiry, or missing code.
    """
    if not student_id or not candidate_code or not isinstance(candidate_code, str):
        return False

    norm_code = candidate_code.strip().upper()
    if len(norm_code) != 8:
        return False

    cand_hash = hashlib.sha256(norm_code.encode("utf-8")).hexdigest()
    now = time.time()
    matched = False

    # 1. Check Redis store
    try:
        from services.redis_service import redis_service
        if redis_service.is_connected:
            cached = redis_service.get_json(f"veritas:pairing:{student_id}")
            if isinstance(cached, dict) and "hash" in cached:
                exp = cached.get("expires_at", 0)
                if now <= exp and hmac.compare_digest(cand_hash, cached["hash"]):
                    matched = True
                    redis_service.delete(f"veritas:pairing:{student_id}")
    except Exception:
        pass

    # 2. Check in-memory store
    with _PAIRING_LOCK:
        stored = _PAIRING_STORE.get(student_id)
        if stored:
            if now <= stored.get("expires_at", 0) and hmac.compare_digest(cand_hash, stored.get("hash", "")):
                matched = True
                _PAIRING_STORE.pop(student_id, None)
            elif now > stored.get("expires_at", 0):
                _PAIRING_STORE.pop(student_id, None)

    return matched


def clear_expired_pairing_codes() -> int:
    """Cleans up expired codes from in-memory fallback store."""
    now = time.time()
    cleared = 0
    with _PAIRING_LOCK:
        expired_keys = [k for k, v in _PAIRING_STORE.items() if now > v.get("expires_at", 0)]
        for k in expired_keys:
            del _PAIRING_STORE[k]
            cleared += 1
    return cleared

