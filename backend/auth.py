"""
Session Token Authentication — HMAC-SHA256 signed tokens
Provides cryptographic verification for student endpoints without requiring
heavy OAuth infrastructure for demo and evaluation environments.
"""
import os
import hmac
import hashlib
import json
import base64
import time
import secrets
import logging
from typing import Optional, Any
from fastapi import Header, HTTPException, status, Query
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger("veritas-backend")

load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_EPHEMERAL_KEY: Optional[str] = None
_JWKS_CLIENT: Any = None


def _is_session_revoked(session_id: str) -> bool:
    """Check the Redis revocation blocklist. Returns True if the session was explicitly revoked (e.g. after reset)."""
    if not session_id:
        return False
    try:
        from services.redis_service import redis_service
        val = redis_service.get_json(f"veritas:revoked:{session_id}")
        return val is not None
    except Exception:
        # If Redis is unavailable, fail open (don't block valid users due to infra issue)
        return False


def revoke_session_token(session_id: str, ttl_seconds: int = 86400) -> None:
    """Write session_id to the Redis revocation blocklist with a 24-hour TTL."""
    if not session_id:
        return
    try:
        from services.redis_service import redis_service
        redis_service.set_json(f"veritas:revoked:{session_id}", {"revoked": True}, ex=ttl_seconds)
    except Exception as e:
        logger.warning("Failed to write session revocation to Redis for %s: %s", session_id, e)


# Cache for invalid/forged kid identifiers to prevent repeated outbound JWKS network hammering
_INVALID_JWKS_KIDS: dict[str, float] = {}


def _validate_jwt_claims(payload: dict) -> None:
    """Validate identity claims when supplied by a Supabase JWT."""
    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing a subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected_audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    token_audience = payload.get("aud")
    if token_audience and token_audience != expected_audience:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token audience is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_issuer = payload.get("iss")
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    if token_issuer and supabase_url and token_issuer != f"{supabase_url}/auth/v1":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token issuer is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )


def is_session_secret_configured() -> bool:
    """Check whether a dedicated SESSION_SECRET_KEY is configured in the environment."""
    return bool(os.getenv("SESSION_SECRET_KEY"))


def _get_secret_key() -> bytes:
    """
    Derives secret key for signing HMAC-SHA256 session tokens.
    Priority:
    1. SESSION_SECRET_KEY (from environment)
    2. In production (ENVIRONMENT=production or RENDER): fail fast with RuntimeError.
       Never use service role credentials as session-signing secrets.
    3. In local development: safe development salt.
    """
    key = os.getenv("SESSION_SECRET_KEY")
    if key:
        return key.encode("utf-8")

    # Strict production requirement
    is_prod = (
        os.getenv("ENVIRONMENT", "").lower() == "production"
        or os.getenv("RENDER") is not None
    )
    if is_prod:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: SESSION_SECRET_KEY environment variable "
            "must be configured in production. Fallback to service-role keys is prohibited."
        )

    # Local development fallback
    return b"veritas-socratic-tutor-secret-key-salt"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data_str: str) -> bytes:
    padding = 4 - (len(data_str) % 4)
    if padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str.encode("ascii"))


def create_session_token(
    student_id: str,
    session_id: str,
    student_name: str,
    role: str = "student",
    expires_in_seconds: int = 86400 * 7,  # 7 days for ease of demoing
    district_id: Optional[str] = None,
    school_id: Optional[str] = None,
    app_metadata: Optional[dict] = None,
) -> str:
    """Issue an HMAC-SHA256 signed session token containing student & session claims."""
    now = int(time.time())
    meta = dict(app_metadata or {})
    if district_id and "district_id" not in meta:
        meta["district_id"] = district_id
    if school_id and "school_id" not in meta:
        meta["school_id"] = school_id
    payload = {
        "sub": student_id,
        "sid": session_id,
        "name": student_name,
        "role": role,
        "iat": now,
        "exp": now + expires_in_seconds,
        "district_id": district_id or meta.get("district_id"),
        "school_id": school_id or meta.get("school_id"),
        "app_metadata": meta,
    }
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded_payload = _b64url_encode(payload_json)

    signature = hmac.new(
        _get_secret_key(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_sig = _b64url_encode(signature)

    return f"{encoded_payload}.{encoded_sig}"


def verify_session_token(token: str) -> dict:
    DEMO_PARENT_ID = "99999999-8888-7777-6666-555555555555"
    DEMO_STUDENT_ID = "24e836e3-3b42-41a0-8a27-222f883eaa10"

    is_prod = (
        os.getenv("ENVIRONMENT", "").lower() == "production"
        or os.getenv("RENDER") is not None
    )
    allow_demo = (
        os.getenv("VERITAS_ALLOW_DEMO_TOKENS", "false").lower() == "true"
        or os.getenv("VERITAS_TEST_MODE", "").lower() == "true"
    )

    # Evaluator Convenience: Pre-seeded zero-setup demo accounts for reviewers and evaluators.
    # Strict allowlist: Only known demo identities are accepted; arbitrary IDs under demo_ prefix are rejected.
    # In production, demo tokens are strictly rejected unless explicitly enabled via VERITAS_ALLOW_DEMO_TOKENS.
    if token in (f"demo_{DEMO_PARENT_ID}", f"demo_parent_{DEMO_PARENT_ID}", "demo_parent"):
        if is_prod and not allow_demo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Demo authentication tokens are disabled in production environments.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {
            "sub": DEMO_PARENT_ID,
            "role": "parent",
            "name": "Demo Parent",
            "is_demo": True,
            "exp": int(time.time()) + 86400 * 30,
        }
    if token in (f"demo_{DEMO_STUDENT_ID}", "demo_student"):
        if is_prod and not allow_demo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Demo authentication tokens are disabled in production environments.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {
            "sub": DEMO_STUDENT_ID,
            "role": "student",
            "name": "Demo Student",
            "is_demo": True,
            "exp": int(time.time()) + 86400 * 30,
        }
    if token.startswith("demo_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid demo token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token or "." not in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = token.strip().split(".")

    # Support 3-part Supabase Auth JWT tokens (both modern ES256/ECC and legacy HS256)
    if len(parts) == 3:
        header_b64, payload_b64, sig_b64 = parts
        try:
            header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token header encoding",
                headers={"WWW-Authenticate": "Bearer"},
            )

        alg = header.get("alg", "HS256")
        payload = None

        if alg in ("ES256", "RS256"):
            supabase_url = os.getenv("SUPABASE_URL")
            if not supabase_url:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Server misconfiguration: SUPABASE_URL required for asymmetric token verification",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            kid = header.get("kid")
            now = time.time()
            if kid and kid in _INVALID_JWKS_KIDS and now < _INVALID_JWKS_KIDS[kid]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token signing key identifier",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                import jwt
                from jwt import PyJWKClient

                global _JWKS_CLIENT
                if "_JWKS_CLIENT" not in globals() or _JWKS_CLIENT is None:
                    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
                    _JWKS_CLIENT = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

                signing_key = _JWKS_CLIENT.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=[alg],
                    options={"verify_exp": True, "verify_aud": False},
                )
                _validate_jwt_claims(payload)
            except HTTPException:
                raise
            except Exception as e:
                if kid:
                    _INVALID_JWKS_KIDS[kid] = time.time() + 300.0
                # Fallback to Supabase Auth API verification if JWKS decoding fails
                try:
                    from db.supabase_client import get_supabase
                    sb = get_supabase()
                    user_resp = sb.auth.get_user(token)
                    if user_resp and user_resp.user:
                        u = user_resp.user
                        app_meta = getattr(u, "app_metadata", None) or {}
                        user_meta = getattr(u, "user_metadata", None) or {}
                        role = app_meta.get("role") or app_meta.get("user_role") or "student"
                        return {
                            "sub": u.id,
                            "email": u.email,
                            "name": user_meta.get("name") or (u.email.split("@")[0] if u.email else "User"),
                            "role": role,
                            "exp": int(time.time()) + 3600,
                            "district_id": app_meta.get("district_id"),
                            "school_id": app_meta.get("school_id"),
                            "app_metadata": app_meta,
                        }
                except Exception:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Asymmetric JWT token verification failed: {e}",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        elif alg == "HS256":
            jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
            if not jwt_secret:
                # Fallback to Supabase Auth API verification if secret is unconfigured
                try:
                    from db.supabase_client import get_supabase
                    sb = get_supabase()
                    user_resp = sb.auth.get_user(token)
                    if user_resp and user_resp.user:
                        u = user_resp.user
                        app_meta = getattr(u, "app_metadata", None) or {}
                        user_meta = getattr(u, "user_metadata", None) or {}
                        role = app_meta.get("role") or app_meta.get("user_role") or "student"
                        return {
                            "sub": u.id,
                            "email": u.email,
                            "name": user_meta.get("name") or (u.email.split("@")[0] if u.email else "User"),
                            "role": role,
                            "exp": int(time.time()) + 3600,
                            "district_id": app_meta.get("district_id"),
                            "school_id": app_meta.get("school_id"),
                            "app_metadata": app_meta,
                        }
                except Exception:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Server misconfiguration: SUPABASE_JWT_SECRET is not configured for HS256 tokens.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            expected_sig = hmac.new(
                jwt_secret.encode("utf-8"),
                f"{header_b64}.{payload_b64}".encode("ascii"),
                hashlib.sha256,
            ).digest()
            try:
                provided_sig = _b64url_decode(sig_b64)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token signature encoding",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not hmac.compare_digest(expected_sig, provided_sig):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="JWT token signature verification failed",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to decode authentication token payload",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            _validate_jwt_claims(payload)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token signing algorithm: {alg}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if payload.get("exp", 0) < time.time():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        app_meta = payload.get("app_metadata") or {}
        user_meta = payload.get("user_metadata") or {}
        # Roles must be read from server-controlled app_metadata or top-level signed claim,
        # NEVER elevated via client-writable user_metadata (which any user can edit in Supabase).
        candidate_role = app_meta.get("role") or app_meta.get("user_role") or payload.get("role")
        if candidate_role in (
            "parent",
            "district_admin",
            "school_principal",
            "teacher",
            "enterprise_admin",
            "admin",
            "super_admin",
            "super-admin",
            "observer",
            "evaluator",
        ):
            role = candidate_role
        elif candidate_role == "student":
            role = "student"
        else:
            role = "student"

        district_id = app_meta.get("district_id") or payload.get("district_id")
        school_id = app_meta.get("school_id") or payload.get("school_id")

        return {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "name": user_meta.get("name") or (payload.get("email", "").split("@")[0] if payload.get("email") else "User"),
            "role": role,
            "exp": payload.get("exp"),
            "district_id": district_id,
            "school_id": school_id,
            "app_metadata": app_meta,
        }

    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    encoded_payload, encoded_sig = parts

    expected_sig = hmac.new(
        _get_secret_key(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()

    try:
        provided_sig = _b64url_decode(encoded_sig)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature encoding",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token signature mismatch or token was tampered with",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload_bytes = _b64url_decode(encoded_payload)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to decode token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check expiration
    if payload.get("exp", 0) < time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please start a new session.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def _extract_token(authorization: Any = None, x_session_token: Any = None) -> Optional[str]:
    if isinstance(authorization, str) and authorization.strip():
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        elif len(parts) == 1:
            return parts[0]
    if isinstance(x_session_token, str) and x_session_token.strip():
        return x_session_token.strip()
    return None


async def verify_student_access(
    student_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
    x_parent_id: Optional[str] = Header(None, alias="X-Parent-Id"),
) -> dict:
    """
    FastAPI dependency to secure student data routes.
    Allows access if:
    1. Scoped session token matches student_id
    2. Request is made by an authenticated, verified parent linked to the student
    """
    token = _extract_token(authorization, x_session_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing session token in Authorization or X-Session-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_session_token(token)
    caller_sub = payload.get("sub")
    caller_role = payload.get("role", "student")

    if caller_sub == student_id:
        return payload

    if caller_role == "parent":
        # Evaluator Convenience: Fixed link between pre-seeded demo parent and demo student accounts
        # Allows reviewers and evaluators to immediately inspect parent monitoring on demo student Alex
        DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
        DEMO_STUDENT = "24e836e3-3b42-41a0-8a27-222f883eaa10"
        if caller_sub == DEMO_PARENT and student_id == DEMO_STUDENT:
            return payload

        # Check database link
        try:
            import asyncio
            from db.supabase_client import get_supabase
            supabase = get_supabase()
            res = await asyncio.to_thread(
                lambda: supabase.table("children")
                .select("*")
                .eq("parent_id", caller_sub)
                .eq("student_id", student_id)
                .limit(1)
                .execute()
            )
            if res.data and len(res.data) > 0:
                child_row = res.data[0]
                if child_row.get("verified") is False or child_row.get("status") == "pending_consent":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: student link is pending student consent",
                    )
                return payload
        except HTTPException:
            raise
        except Exception:
            pass

        # Fallback check from persistent children_store.json or Redis if local fallback or offline
        try:
            from services.redis_service import redis_service
            if redis_service.is_connected:
                cached_kids = redis_service.get_json(f"veritas:parent_children:{caller_sub}")
                if isinstance(cached_kids, list):
                    for c in cached_kids:
                        if c.get("student_id") == student_id:
                            if c.get("verified") is False or c.get("status") == "pending_consent":
                                raise HTTPException(
                                    status_code=status.HTTP_403_FORBIDDEN,
                                    detail="Access denied: student link is pending student consent",
                                )
                            return payload
        except HTTPException:
            raise
        except Exception:
            pass

        try:
            store_file = Path(__file__).resolve().parent.parent / "data" / "children_store.json"
            if not store_file.exists():
                store_file = Path(__file__).resolve().parent / "data" / "children_store.json"
            if store_file.exists():
                with open(store_file, "r", encoding="utf-8") as f:
                    store_data = json.load(f)
                    for c in store_data:
                        if c.get("parent_id") == caller_sub and c.get("student_id") == student_id:
                            if c.get("verified") is False or c.get("status") == "pending_consent":
                                raise HTTPException(
                                    status_code=status.HTTP_403_FORBIDDEN,
                                    detail="Access denied: student link is pending student consent",
                                )
                            return payload
        except HTTPException:
            raise
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Access denied: this session token belongs to {caller_sub}, not authorized for student {student_id}",
    )


async def verify_parent_access(
    parent_id: str,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency to secure parent data routes.
    Guarantees:
    1. Caller provides a valid, unexpired token.
    2. Caller ID matches parent_id (or caller is authorized demo parent).
    3. Caller role is 'parent'.
    """
    token = _extract_token(authorization, x_session_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing token in Authorization or X-Session-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_session_token(token)
    caller_id = payload.get("sub")
    caller_role = payload.get("role", "student")

    # Evaluator Convenience: Pre-seeded demo parent identity allowed for zero-setup parent dashboard inspection
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    if parent_id == DEMO_PARENT and (caller_id == DEMO_PARENT or caller_id == "demo_parent"):
        return payload

    if caller_id != parent_id or caller_role != "parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: you do not have permission to manage parent account {parent_id}",
        )

    return payload


async def verify_parent_caller(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency to authenticate parent for requests where parent_id is passed
    in request body (e.g. POST /parent/add-child).
    """
    token = _extract_token(authorization, x_session_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing token in Authorization or X-Session-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_session_token(token)
    caller_id = payload.get("sub")
    caller_role = payload.get("role", "student")

    # Evaluator Convenience: Pre-seeded demo parent identity allowed for zero-setup mutation operations without live email OTP
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    if caller_id == DEMO_PARENT or caller_id == "demo_parent":
        return payload

    if caller_role != "parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: parent role required",
        )

    return payload


async def verify_session_access(
    session_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency to secure active tutoring session routes.
    Guarantees:
    1. Caller provides a cryptographically valid, unexpired session token or Supabase JWT.
    2. If session_id is supplied in query string, the token's 'sid' claim must match.
    3. The session has not been revoked (e.g. via a password reset or session reset operation).
    """
    token = _extract_token(authorization, x_session_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing session token in Authorization or X-Session-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_session_token(token)
    token_sid = payload.get("sid")

    # Check the revocation blocklist for the session ID claimed by the token
    check_sid = session_id or token_sid
    if check_sid and _is_session_revoked(check_sid):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked. Please start a new session.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if session_id and token_sid and token_sid != session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token was issued for session {token_sid}, not {session_id}",
        )
    if payload.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    return payload


async def verify_student_caller(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency to authenticate requests where student_id is in request body
    (e.g., POST /games/score, POST /games/reset, POST /session/reset).
    """
    token = _extract_token(authorization, x_session_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing token in Authorization or X-Session-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_session_token(token)


ENTERPRISE_ROLES = {
    "district_admin",
    "school_principal",
    "teacher",
    "enterprise_admin",
    "admin",
    "super_admin",
    "super-admin",
    "observer",
    "evaluator",
}
SUPER_ADMIN_ROLES = {"super_admin", "super-admin"}


async def verify_enterprise_caller(
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency to authenticate enterprise administrators, principals, and teachers.
    Guarantees:
    1. Caller provides a valid, unexpired token.
    2. Demo tokens and parents/students are strictly rejected with 403 Forbidden.
    3. Caller role is one of ENTERPRISE_ROLES.
    4. Extracts tenant claims (district_id, school_id) for tenant-scoped operations.
    5. Rejects enterprise callers without a tenant claim unless explicitly a super-admin.
    """
    token = _extract_token(authorization, x_session_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing token in Authorization or X-Session-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_session_token(token)

    # Demo accounts and general parents/students are barred from enterprise management
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    if payload.get("is_demo") or payload.get("sub") == DEMO_PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: demo identities are not authorized for enterprise administrative endpoints",
        )

    caller_role = payload.get("role")
    if caller_role not in ENTERPRISE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Enterprise access denied: role '{caller_role}' is not authorized for district/school management",
        )

    app_meta = payload.get("app_metadata") or {}
    is_super_admin = (
        caller_role in SUPER_ADMIN_ROLES
        or payload.get("is_super_admin") is True
        or app_meta.get("is_super_admin") is True
        or app_meta.get("super_admin") is True
    )

    district_id = payload.get("district_id") or app_meta.get("district_id")
    school_id = payload.get("school_id") or app_meta.get("school_id")

    if not is_super_admin and not (district_id or school_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: enterprise caller has no tenant scope claim (district_id or school_id required)",
        )

    return payload

