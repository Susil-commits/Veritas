"""Supabase client singleton for the backend."""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        is_production = (
            os.environ.get("ENVIRONMENT", "").lower() == "production"
            or os.environ.get("RENDER") is not None
        )
        if is_production and not service_role_key:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required in production.")
        key = service_role_key or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY environment variables.")
        _client = create_client(url, key)
    return _client
