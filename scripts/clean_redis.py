"""
Redis Inspector & Cleanup Utility for Veritas.
Safely inspects active connections, analyzes command consumers,
and purges stale keys to protect Upstash serverless quotas.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
        getattr(sys.stderr, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

# Load backend environment variables
backend_env = Path(__file__).resolve().parent.parent / "backend" / ".env"
root_env = Path(__file__).resolve().parent.parent / ".env"
if backend_env.exists():
    load_dotenv(backend_env)
if root_env.exists():
    load_dotenv(root_env)

try:
    import redis
except ImportError:
    print("[ERROR] redis-py is not installed. Install via: pip install redis")
    sys.exit(1)


def get_redis_client():
    redis_url = os.getenv("REDIS_URI") or os.getenv("REDIS_URL") or os.getenv("UPSTASH_REDIS_URL")
    if not redis_url:
        print("[ERROR] No REDIS_URL or REDIS_URI found in environment files.")
        sys.exit(1)
    return redis.from_url(redis_url, decode_responses=True)


def inspect_redis(r):
    print("=" * 60)
    print("           UPSTASH REDIS DIAGNOSTIC REPORT")
    print("=" * 60)

    try:
        r.ping()
        print("✓ Connectivity: ONLINE & REACHABLE")
    except Exception as e:
        print(f"✗ Connectivity FAILED: {e}")
        return

    # Check active clients
    try:
        clients = r.client_list()
        print(f"\n[ACTIVE CLIENT CONNECTIONS: {len(clients)}]")
        for c in clients:
            addr = c.get("addr", "unknown")
            name = c.get("name", "")
            lib = c.get("lib-name", "unknown")
            print(f"  • {addr} | lib: {lib} | name: {name or '(none)'}")
    except Exception as e:
        print(f"  (Could not fetch client list: {e})")

    # List keys
    keys = r.keys("*")
    print(f"\n[CURRENT STORED KEYS: {len(keys)}]")
    if not keys:
        print("  (Database is completely empty)")
    for k in keys:
        k_type = r.type(k)
        ttl = r.ttl(k)
        ttl_str = f"{ttl}s" if ttl > 0 else ("no expiry" if ttl == -1 else "expired")
        print(f"  • {k} [{k_type}] (TTL: {ttl_str})")

    print("=" * 60)
    return keys


def clean_keys(r, pattern="*"):
    keys = r.keys(pattern)
    if not keys:
        print(f"No keys matched pattern '{pattern}'. Nothing to clean.")
        return 0

    print(f"Deleting {len(keys)} keys matching '{pattern}'...")
    deleted = r.delete(*keys)
    print(f"✓ Successfully deleted {deleted} keys.")
    return deleted


if __name__ == "__main__":
    r = get_redis_client()
    keys = inspect_redis(r)

    if "--clean" in sys.argv or "--all" in sys.argv:
        clean_keys(r, "*")
    elif "--veritas-only" in sys.argv:
        clean_keys(r, "veritas:*")
    else:
        print("\nTo clean keys, run:")
        print("  python scripts/clean_redis.py --clean         (Deletes all keys)")
        print("  python scripts/clean_redis.py --veritas-only  (Deletes veritas:* keys only)")
