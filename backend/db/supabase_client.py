"""Supabase client singleton for the backend."""
import os
import logging
from typing import Any
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("veritas-backend.db")

_client: Any = None


class MockResponse:
    def __init__(self, data=None):
        self.data = data or []


class MockQueryBuilder:
    def __init__(self, table_name: str, store: dict):
        self.table_name = table_name
        self.store = store
        self._filters: list[tuple[str, Any]] = []
        self._limit_val: int | None = None
        self._action = "select"
        self._payload: Any = None

    def select(self, *args, **kwargs):
        return self

    def insert(self, payload, *args, **kwargs):
        self._action = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, *args, **kwargs):
        self._action = "upsert"
        self._payload = payload
        return self

    def update(self, payload, *args, **kwargs):
        self._action = "update"
        self._payload = payload
        return self

    def delete(self, *args, **kwargs):
        self._action = "delete"
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def neq(self, column: str, value: Any):
        return self

    def in_(self, column: str, values: list):
        return self

    def order(self, column: str, desc: bool = False):
        return self

    def limit(self, count: int):
        self._limit_val = count
        return self

    def execute(self):
        table = self.store.setdefault(self.table_name, [])
        if self._action == "insert":
            records = self._payload if isinstance(self._payload, list) else [self._payload]
            for r in records:
                table.append(dict(r))
            return MockResponse(records)
        elif self._action == "upsert":
            records = self._payload if isinstance(self._payload, list) else [self._payload]
            for r in records:
                r_id = r.get("id")
                matched = False
                if r_id:
                    for i, existing in enumerate(table):
                        if existing.get("id") == r_id:
                            table[i] = dict(r)
                            matched = True
                            break
                if not matched:
                    table.append(dict(r))
            return MockResponse(records)
        elif self._action == "delete":
            deleted = []
            remaining = []
            for item in table:
                match = True
                for col, val in self._filters:
                    if item.get(col) != val:
                        match = False
                        break
                if match:
                    deleted.append(item)
                else:
                    remaining.append(item)
            self.store[self.table_name] = remaining
            return MockResponse(deleted)
        else:  # select
            res = []
            for item in table:
                match = True
                for col, val in self._filters:
                    if item.get(col) != val:
                        match = False
                        break
                if match:
                    res.append(dict(item))
            if self._limit_val is not None:
                res = res[:self._limit_val]
            return MockResponse(res)


class HermeticSupabaseClient:
    def __init__(self):
        self._store: dict[str, list] = {}
        # Pre-seed curriculum standards in mock
        self._store["skills"] = [
            {"id": "4.NF.A.1", "name": "Equivalent fractions", "cc_standard": "4.NF.A.1", "sequence_order": 4},
            {"id": "4.NF.B.3", "name": "Adding and subtracting fractions", "cc_standard": "4.NF.B.3", "sequence_order": 5},
            {"id": "6.EE.B.7", "name": "Solving one-step equations", "cc_standard": "6.EE.B.7", "sequence_order": 9},
        ]

    def table(self, table_name: str):
        return MockQueryBuilder(table_name, self._store)

    @property
    def auth(self):
        class MockAuth:
            def get_user(self, token: str):
                return None
        return MockAuth()


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
            if is_production:
                raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in production.")
            logger.info("SUPABASE_URL not configured: using hermetic in-memory mock client for tests.")
            _client = HermeticSupabaseClient()
            return _client
        _client = create_client(url, key)
    return _client
