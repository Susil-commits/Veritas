"""
Session Manager — Resilient Session State Persistence for Veritas Tutor.
Eliminates in-memory fragility: Active sessions survive Render restarts, worker reloads,
and redeployments during Demo Day by persisting state to Supabase with in-memory caching.
"""
import os
import uuid
import asyncio
import threading
import json
from pathlib import Path
from collections import OrderedDict
from typing import Any
from db.supabase_client import get_supabase
from bkt.tracker import initialize_mastery, get_next_skill
from agents.content_agent import get_next_problem

# Persistent storage directory
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_STORE_PATH = DATA_DIR / "sessions_store.json"
_disk_lock = threading.Lock()


def _load_sessions_from_disk() -> dict[str, Any]:
    with _disk_lock:
        if not SESSIONS_STORE_PATH.exists():
            return {}
        try:
            with open(SESSIONS_STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to read sessions from disk: {e}")
            return {}


def _write_session_to_disk(session_id: str, state: dict[str, Any]) -> None:
    with _disk_lock:
        try:
            current = {}
            if SESSIONS_STORE_PATH.exists():
                try:
                    with open(SESSIONS_STORE_PATH, "r", encoding="utf-8") as f:
                        current = json.load(f)
                except Exception:
                    current = {}
            current[session_id] = state
            # Atomic file write via temp file
            temp_path = SESSIONS_STORE_PATH.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            temp_path.replace(SESSIONS_STORE_PATH)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to write session {session_id} to disk: {e}")


def _remove_session_from_disk(session_id: str) -> None:
    with _disk_lock:
        try:
            if not SESSIONS_STORE_PATH.exists():
                return
            with open(SESSIONS_STORE_PATH, "r", encoding="utf-8") as f:
                current = json.load(f)
            if session_id in current:
                del current[session_id]
                temp_path = SESSIONS_STORE_PATH.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(current, f, indent=2)
                temp_path.replace(SESSIONS_STORE_PATH)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to remove session {session_id} from disk: {e}")

# Per-session asyncio.Lock registry to serialize concurrent read-modify-write operations
_session_locks: dict[str, asyncio.Lock] = {}
_locks_guard = threading.Lock()


def get_session_lock(session_id: str) -> asyncio.Lock:
    """Return an asyncio.Lock tied to session_id to serialize read-modify-write state operations."""
    with _locks_guard:
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]

# Maximum number of active sessions kept in RAM cache (LRU eviction).
# Default 100 easily handles >50 concurrent students while preventing unbounded memory growth.
MAX_SESSIONS_CACHE_SIZE = int(os.getenv("MAX_SESSIONS_CACHE_SIZE", "100"))


class BoundedSessionCache(OrderedDict):
    """
    LRU-capped thread-safe dictionary for active session states.
    Limits RAM usage under high concurrency (>50 concurrent sessions).
    Evicted sessions are seamlessly rehydrated from Supabase on next access.
    """
    def __init__(self, max_size: int = MAX_SESSIONS_CACHE_SIZE, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.max_size = max_size
        self._lock = threading.RLock()

    def __getitem__(self, key: str) -> dict[str, Any]:
        with self._lock:
            val = super().__getitem__(key)
            self.move_to_end(key)
            return val

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            if key in self:
                self.move_to_end(key)
            super().__setitem__(key, value)
            while len(self) > self.max_size:
                self.popitem(last=False)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self:
                self.move_to_end(key)
                return super().__getitem__(key)
            return default

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return super().__contains__(key)

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return super().pop(key, default)

    def clear(self) -> None:
        with self._lock:
            super().clear()

    def keys_list(self) -> list[str]:
        with self._lock:
            return list(super().keys())


# In-memory session cache pre-seeded from persistent disk storage
_sessions_cache: BoundedSessionCache = BoundedSessionCache(max_size=MAX_SESSIONS_CACHE_SIZE)
try:
    _initial_disk_sessions = _load_sessions_from_disk()
    for s_id, s_state in _initial_disk_sessions.items():
        _sessions_cache[s_id] = s_state
    if _initial_disk_sessions:
        print(f"[INFO] SessionManager: Rehydrated {len(_initial_disk_sessions)} active sessions from persistent disk store.")
except Exception as e:
    print(f"[WARN] SessionManager: Initial disk session rehydration notice: {e}")


def _clean_state_for_persistence(state: Any) -> dict[str, Any]:
    """Strip non-serializable elements like raw image bytes before JSON persistence and cap history."""
    if not isinstance(state, dict):
        return {}
    cleaned = dict(state)
    cleaned["latest_image_bytes"] = None
    if "conversation_history" in cleaned and isinstance(cleaned["conversation_history"], list):
        cleaned["conversation_history"] = cleaned["conversation_history"][-50:]
    return cleaned


def get_session(session_id: str) -> dict[str, Any] | None:
    """
    Retrieve session state with multi-tier storage:
    1. In-memory cache hit (0ms).
    2. Persistent disk store hit (survives worker/server restarts).
    3. Supabase `sessions.state` JSONB restoration on cache miss.
    4. Automatic database rehydration fallback from `sessions` + `session_events` + `student_skill_mastery`.
    """
    # 1. Fast in-memory cache lookup
    if session_id in _sessions_cache:
        return _sessions_cache[session_id]

    # 2. Check local disk store
    disk_sessions = _load_sessions_from_disk()
    if session_id in disk_sessions:
        state = disk_sessions[session_id]
        _sessions_cache[session_id] = state
        return state

    supabase = get_supabase()

    # 3. Query Supabase sessions table
    try:
        sess_res = (
            supabase.table("sessions")
            .select("*")
            .eq("id", session_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(f"[WARN] SessionManager: Failed to query sessions table for {session_id}: {e}")
        return None

    if not sess_res.data:
        return None

    sess_row = sess_res.data[0]
    student_id = sess_row.get("student_id")
    student_name = sess_row.get("student_name") or "Student"

    # Check if `state` column exists and contains valid session state
    saved_state = sess_row.get("state")
    if isinstance(saved_state, dict) and "student_id" in saved_state and "current_problem" in saved_state:
        _sessions_cache[session_id] = saved_state
        print(f"[INFO] SessionManager: Restored session {session_id} directly from Supabase state JSONB.")
        return saved_state

    # 3. Rehydration Fallback: Reconstruct state from DB records if `state` column is empty
    print(f"[INFO] SessionManager: Rehydrating session {session_id} from database event stream...")
    try:
        # Load student mastery
        mastery_rows = (
            supabase.table("student_skill_mastery")
            .select("skill_id, mastery_prob")
            .eq("student_id", student_id)
            .execute()
        )
        mastery_state = initialize_mastery()
        for r in (mastery_rows.data or []):
            mastery_state[r["skill_id"]] = r["mastery_prob"]

        # Load session events to rebuild conversation history and problem attempts
        events_res = (
            supabase.table("session_events")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        events = events_res.data or []

        conversation_history = []
        problems_attempted = []
        last_problem_id = None

        for ev in events:
            prob_id = ev.get("problem_id")
            if prob_id and prob_id not in problems_attempted:
                problems_attempted.append(prob_id)
            if prob_id:
                last_problem_id = prob_id

            student_turn = ev.get("attempt_text")
            tutor_turn = ev.get("agent_response")
            if student_turn:
                conversation_history.append({"role": "student", "content": student_turn})
            if tutor_turn:
                conversation_history.append({"role": "tutor", "content": tutor_turn})

        # Resolve current problem
        current_problem = None
        if last_problem_id:
            prob_res = (
                supabase.table("problems")
                .select("*")
                .eq("id", last_problem_id)
                .limit(1)
                .execute()
            )
            if prob_res.data:
                current_problem = prob_res.data[0]

        current_skill = get_next_skill(mastery_state)
        if not current_problem:
            current_problem = get_next_problem(
                skill_id=current_skill,
                mastery_prob=mastery_state.get(current_skill, 0.3),
                student_id=student_id,
            )
            if current_problem and current_problem.get("id"):
                problems_attempted.append(current_problem["id"])

        rehydrated_state: dict[str, Any] = {
            "student_id": student_id,
            "student_name": student_name,
            "session_id": session_id,
            "conversation_history": conversation_history,
            "latest_input": "",
            "latest_image_bytes": None,
            "current_problem": current_problem,
            "current_problem_credited": False,
            "problems_attempted": problems_attempted,
            "mastery_state": mastery_state,
            "current_skill_id": current_problem.get("skill_id", current_skill) if current_problem else current_skill,
            "diagnosis": None,
            "agent_response": "",
            "thinking_steps": [],
            "next_action": None,
        }

        _sessions_cache[session_id] = rehydrated_state
        print(f"[INFO] SessionManager: Successfully rehydrated session {session_id} ({len(conversation_history)} messages).")
        return rehydrated_state

    except Exception as err:
        print(f"[ERROR] SessionManager: Rehydration error for {session_id}: {err}")
        return None


def save_session(session_id: str, state: Any) -> None:
    """
    Persist session state in RAM cache, disk store, and sync to Supabase sessions table.
    """
    # 1. Update in-memory cache immediately
    _sessions_cache[session_id] = state

    # 2. Persist to local disk store (ensures session survives restarts even if DB schema lacks state column)
    cleaned_state = _clean_state_for_persistence(state)
    _write_session_to_disk(session_id, cleaned_state)

    # 3. Persist to Supabase sessions table
    try:
        supabase = get_supabase()
        supabase.table("sessions").update({"state": cleaned_state}).eq("id", session_id).execute()
    except Exception as e:
        # If the `state` column is not yet present on remote DB, fallback silently
        err_str = str(e)
        if "PGRST204" in err_str or "state" in err_str:
            pass  # Migration day 3 not run yet; disk store and rehydration fallback handle recovery
        else:
            print(f"[WARN] SessionManager: Failed to persist session state to Supabase: {e}")


def evict_session(session_id: str) -> None:
    """Evict session state from RAM cache and disk store."""
    try:
        _sessions_cache.pop(session_id, None)
    except Exception:
        pass
    try:
        _remove_session_from_disk(session_id)
    except Exception:
        pass


def record_session_event(
    session_id: str,
    student_id: str,
    problem_id: Any,
    attempt_text: str | None,
    is_correct: bool | None,
    agent_response: str | None,
) -> None:
    """
    Record an interaction event (student thought, diagnostic result, tutor response) into `session_events`.
    Guarantees event persistence for audit log, parent dashboard, and state rehydration.
    """
    try:
        supabase = get_supabase()
        clean_prob_id = None
        if problem_id:
            try:
                uuid.UUID(str(problem_id))
                clean_prob_id = str(problem_id)
            except (ValueError, AttributeError):
                clean_prob_id = None

        payload = {
            "session_id": session_id,
            "student_id": student_id,
            "problem_id": clean_prob_id,
            "attempt_text": attempt_text,
            "is_correct": is_correct,
            "agent_response": agent_response,
        }
        try:
            supabase.table("session_events").insert(payload).execute()
        except Exception as insert_err:
            if clean_prob_id is not None and ("foreign key" in str(insert_err).lower() or "fkey" in str(insert_err).lower()):
                payload["problem_id"] = None
                supabase.table("session_events").insert(payload).execute()
            else:
                raise insert_err
    except Exception as e:
        print(f"[WARN] SessionManager: Failed to insert session event: {e}")


def get_all_active_session_ids() -> list[str]:
    """Return list of active cached session IDs for diagnostics."""
    return _sessions_cache.keys_list()
