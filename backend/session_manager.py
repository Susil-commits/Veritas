"""
Session Manager — Resilient Session State Persistence for Veritas Tutor.
Supabase-backed session state allows recovery across application-instance restarts;
local disk is a best-effort development fallback, backed by an LRU in-memory cache.
"""
import os
import uuid
import asyncio
import threading
import json
import datetime
import time
from pathlib import Path
from collections import OrderedDict
from typing import Any
from db.supabase_client import get_supabase
from bkt.tracker import initialize_mastery, get_next_skill
from agents.content_agent import get_next_problem
from services.redis_service import redis_service

# Persistent storage directory
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_STORE_PATH = DATA_DIR / "sessions_store.json"
_disk_lock = threading.Lock()
_disk_sessions_memory: dict[str, Any] | None = None

# Persistent misconception tracking store (longitudinal diagnostic model beside BKT)
MISCONCEPTIONS_STORE_PATH = DATA_DIR / "misconceptions_store.json"
_misconceptions_lock = threading.Lock()
_misconceptions_memory: dict[str, dict[str, Any]] | None = None


def _load_sessions_from_disk() -> dict[str, Any]:
    global _disk_sessions_memory
    with _disk_lock:
        if _disk_sessions_memory is not None:
            return _disk_sessions_memory
        if not SESSIONS_STORE_PATH.exists():
            _disk_sessions_memory = {}
            return _disk_sessions_memory
        try:
            with open(SESSIONS_STORE_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                _disk_sessions_memory = loaded if isinstance(loaded, dict) else {}
                return _disk_sessions_memory
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to read sessions from disk: {e}")
            _disk_sessions_memory = {}
            return _disk_sessions_memory


def _write_session_to_disk(session_id: str, state: dict[str, Any]) -> None:
    global _disk_sessions_memory
    with _disk_lock:
        try:
            if _disk_sessions_memory is None:
                if SESSIONS_STORE_PATH.exists():
                    try:
                        with open(SESSIONS_STORE_PATH, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                            _disk_sessions_memory = loaded if isinstance(loaded, dict) else {}
                    except Exception:
                        _disk_sessions_memory = {}
                else:
                    _disk_sessions_memory = {}
            store = _disk_sessions_memory
            store[session_id] = state
            # Atomic file write via temp file with fast serialization
            temp_path = SESSIONS_STORE_PATH.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(store, f, separators=(",", ":"))
            temp_path.replace(SESSIONS_STORE_PATH)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to write session {session_id} to disk: {e}")


def _remove_session_from_disk(session_id: str) -> None:
    global _disk_sessions_memory
    with _disk_lock:
        try:
            if _disk_sessions_memory is None:
                if SESSIONS_STORE_PATH.exists():
                    try:
                        with open(SESSIONS_STORE_PATH, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                            _disk_sessions_memory = loaded if isinstance(loaded, dict) else {}
                    except Exception:
                        _disk_sessions_memory = {}
                else:
                    _disk_sessions_memory = {}
            store = _disk_sessions_memory
            if session_id in store:
                del store[session_id]
                temp_path = SESSIONS_STORE_PATH.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(store, f, separators=(",", ":"))
                temp_path.replace(SESSIONS_STORE_PATH)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to remove session {session_id} from disk: {e}")


# Per-session asyncio.Lock registry to serialize concurrent read-modify-write operations
_session_locks: dict[str, asyncio.Lock] = {}
_session_lock_times: dict[str, float] = {}
_locks_guard = threading.Lock()
MAX_SESSION_LOCKS = int(os.getenv("MAX_SESSION_LOCKS", "10000"))


def get_session_lock(session_id: str) -> asyncio.Lock:
    """Return an asyncio.Lock tied to session_id to serialize read-modify-write state operations."""
    _LOCK_IDLE_TTL = 7200  # 2 hours — locks not accessed for this long are eligible for eviction
    with _locks_guard:
        now = time.time()
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        _session_lock_times[session_id] = now
        if len(_session_locks) > MAX_SESSION_LOCKS:
            # Prefer evicting locks that are (a) unlocked AND (b) oldest by last-access time
            # Fallback: also evict locks idle for >2h even if they appear locked (stale context)
            stale_ids = sorted(_session_lock_times, key=_session_lock_times.get)
            for stale_id in stale_ids:
                if stale_id == session_id:
                    continue
                stale_lock = _session_locks.get(stale_id)
                if stale_lock is None:
                    _session_lock_times.pop(stale_id, None)
                    continue
                last_access = _session_lock_times.get(stale_id, 0)
                is_idle_too_long = (now - last_access) > _LOCK_IDLE_TTL
                if not stale_lock.locked() or is_idle_too_long:
                    _session_locks.pop(stale_id, None)
                    _session_lock_times.pop(stale_id, None)
                if len(_session_locks) <= MAX_SESSION_LOCKS:
                    break
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
    """Strip non-serializable elements, private problem metadata, and cap history before JSON persistence."""
    if not isinstance(state, dict):
        return {}
    cleaned = dict(state)
    # Never persist raw image bytes
    cleaned["latest_image_bytes"] = None
    # Strip the full private problem object (contains expected_steps, answer, solution, embedding)
    # The public-facing current_problem is stored separately and is already sanitised by _public_problem()
    cleaned.pop("current_problem_evaluation", None)
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

    def fallback_state() -> dict[str, Any] | None:
        try:
            redis_state = redis_service.get_json(f"veritas:session:{session_id}")
            if isinstance(redis_state, dict) and "student_id" in redis_state:
                _sessions_cache[session_id] = redis_state
                return redis_state
        except Exception:
            pass
        disk_sessions = _load_sessions_from_disk()
        if session_id in disk_sessions:
            state = disk_sessions[session_id]
            _sessions_cache[session_id] = state
            return state
        return None

    supabase = get_supabase()

    # Query the authoritative database before distributed/local fallbacks.
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
        return fallback_state()

    if not sess_res.data:
        return fallback_state()

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
                s_turn = {"role": "student", "content": student_turn}
                if prob_id:
                    s_turn["problem_id"] = prob_id
                conversation_history.append(s_turn)
            if tutor_turn:
                t_turn = {"role": "tutor", "content": tutor_turn}
                if prob_id:
                    t_turn["problem_id"] = prob_id
                conversation_history.append(t_turn)

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
            "active_misconceptions": get_student_misconceptions(student_id),
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
    Persist session state in RAM cache, disk store, Redis, and sync to Supabase sessions table.
    """
    # 1. Update in-memory cache immediately
    _sessions_cache[session_id] = state

    # 2. Persist to local disk store (ensures session survives restarts even if DB schema lacks state column)
    cleaned_state = _clean_state_for_persistence(state)
    _write_session_to_disk(session_id, cleaned_state)

    # 3. Synchronize to distributed Redis (7-day TTL)
    try:
        redis_service.set_json(f"veritas:session:{session_id}", cleaned_state, ex=7 * 86400)
    except Exception as re_err:
        pass

    # 4. Persist to Supabase sessions table
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
    """Evict session state from RAM cache, disk store, Redis, and release associated asyncio locks."""
    try:
        _sessions_cache.pop(session_id, None)
    except Exception:
        pass
    try:
        _remove_session_from_disk(session_id)
    except Exception:
        pass
    try:
        redis_service.delete(f"veritas:session:{session_id}")
    except Exception:
        pass
    try:
        with _locks_guard:
            _session_locks.pop(session_id, None)
            _session_lock_times.pop(session_id, None)
    except Exception:
        pass


def evict_student_sessions(student_id: str) -> None:
    """Evict all cached, disk-persisted, and Redis sessions belonging to a specific student."""
    # 1. Evict from in-memory cache (and Redis via evict_session)
    try:
        keys_to_evict = []
        for sid in _sessions_cache.keys_list():
            sess = _sessions_cache.get(sid)
            if isinstance(sess, dict) and sess.get("student_id") == student_id:
                keys_to_evict.append(sid)
        for sid in keys_to_evict:
            evict_session(sid)
    except Exception as e:
        print(f"[WARN] SessionManager: Failed to evict student sessions from cache: {e}")

    # 2. Evict from disk store
    global _disk_sessions_memory
    with _disk_lock:
        try:
            if _disk_sessions_memory:
                disk_to_evict = [
                    sid for sid, sess in _disk_sessions_memory.items()
                    if isinstance(sess, dict) and sess.get("student_id") == student_id
                ]
                if disk_to_evict:
                    for sid in disk_to_evict:
                        del _disk_sessions_memory[sid]
                    temp_path = SESSIONS_STORE_PATH.with_suffix(".tmp")
                    with open(temp_path, "w", encoding="utf-8") as f:
                        json.dump(_disk_sessions_memory, f, separators=(",", ":"))
                    temp_path.replace(SESSIONS_STORE_PATH)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to remove student sessions from disk: {e}")

    # 3. Also delete any Redis session keys for this student that were NOT in the memory cache
    #    (handles sessions that were only present in Redis — e.g. after a worker restart).
    try:
        supabase = get_supabase()
        db_sessions = (
            supabase.table("sessions")
            .select("id")
            .eq("student_id", student_id)
            .execute()
        )
        for row in (db_sessions.data or []):
            sid = row.get("id")
            if sid:
                try:
                    redis_service.delete(f"veritas:session:{sid}")
                except Exception:
                    pass
    except Exception as e:
        print(f"[WARN] SessionManager: Could not enumerate Supabase sessions for Redis cleanup: {e}")



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


def _load_misconceptions_from_disk() -> dict[str, dict[str, Any]]:
    global _misconceptions_memory
    with _misconceptions_lock:
        if _misconceptions_memory is not None:
            return _misconceptions_memory
        if not MISCONCEPTIONS_STORE_PATH.exists():
            _misconceptions_memory = {}
            return _misconceptions_memory
        try:
            with open(MISCONCEPTIONS_STORE_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                _misconceptions_memory = loaded if isinstance(loaded, dict) else {}
                return _misconceptions_memory
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to read misconceptions from disk: {e}")
            _misconceptions_memory = {}
            return _misconceptions_memory


def _write_misconceptions_to_disk() -> None:
    global _misconceptions_memory
    with _misconceptions_lock:
        try:
            if _misconceptions_memory is None:
                _misconceptions_memory = {}
            temp_path = MISCONCEPTIONS_STORE_PATH.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(_misconceptions_memory, f, separators=(",", ":"))
            temp_path.replace(MISCONCEPTIONS_STORE_PATH)
        except Exception as e:
            print(f"[WARN] SessionManager: Failed to write misconceptions to disk: {e}")


def get_student_misconceptions(student_id: str) -> dict[str, dict[str, Any]]:
    """Retrieve all tracked misconceptions and resolution status for a student."""
    all_misc = _load_misconceptions_from_disk()
    return dict(all_misc.get(student_id, {}))


def save_student_misconception(
    student_id: str,
    misconception_type: str,
    skill_id: str,
    resolved: bool = False,
) -> dict[str, Any]:
    """
    Record or update a diagnosed misconception occurrence in longitudinal student profile:
    {
      "count": N,
      "last_seen": "<ISO_TIMESTAMP>",
      "resolved": false,
      "skill_id": "<SKILL_ID>"
    }
    """
    all_misc = _load_misconceptions_from_disk()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    student_misc = all_misc.setdefault(student_id, {})
    entry = student_misc.get(misconception_type, {
        "count": 0,
        "last_seen": now_iso,
        "resolved": False,
        "skill_id": skill_id or "",
    })
    if not resolved:
        entry["count"] = entry.get("count", 0) + 1
        entry["last_seen"] = now_iso
        entry["resolved"] = False
        if skill_id:
            entry["skill_id"] = skill_id
    else:
        entry["resolved"] = True
        entry["resolved_at"] = now_iso
    student_misc[misconception_type] = entry
    _write_misconceptions_to_disk()
    return entry


def resolve_student_misconceptions_for_skill(student_id: str, skill_id: str) -> list[str]:
    """Mark all active misconceptions associated with skill_id as resolved."""
    all_misc = _load_misconceptions_from_disk()
    student_misc = all_misc.get(student_id, {})
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resolved_types = []
    for m_type, entry in student_misc.items():
        if entry.get("skill_id") == skill_id and not entry.get("resolved", False):
            entry["resolved"] = True
            entry["resolved_at"] = now_iso
            resolved_types.append(m_type)
    if resolved_types:
        _write_misconceptions_to_disk()
    return resolved_types


def clear_student_misconceptions(student_id: str) -> None:
    """Clear student misconceptions store upon session/profile reset."""
    all_misc = _load_misconceptions_from_disk()
    if student_id in all_misc:
        del all_misc[student_id]
        _write_misconceptions_to_disk()


def get_all_active_session_ids() -> list[str]:
    """Return list of active cached session IDs for diagnostics."""
    return _sessions_cache.keys_list()
