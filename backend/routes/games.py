"""
Math Arcade & Curriculum-Gated Games Progression endpoints.
"""
import os
import json
import datetime
import threading
from typing import Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from db.supabase_client import get_supabase
from auth import verify_student_access, verify_student_caller
from bkt.tracker import initialize_mastery
from session_manager import get_all_active_session_ids, get_session
from routes.common import db_exec, logger, BACKEND_DIR

router = APIRouter(prefix="/games", tags=["Math Arcade"])

GAMES_DATA_DIR = BACKEND_DIR / "data"
GAMES_DATA_DIR.mkdir(parents=True, exist_ok=True)
GAMES_STORE_PATH = GAMES_DATA_DIR / "games_store.json"
_games_store_lock = threading.RLock()

GAME_LEVELS_CONFIG = [
    {
        "id": "multiplier_matrix",
        "level": 1,
        "name": "Multiplier Matrix",
        "subtitle": "Space Blitz",
        "theme": "space",
        "skill_required": "3.OA.A.1",
        "skill_name": "Understanding Multiplication",
        "unlock_requirement": "Complete Multiplication part (3.OA.A.1) to unlock",
        "description": "Defend the spacecraft by bursting plasma product bubbles before math meteors strike!",
    },
    {
        "id": "division_dungeons",
        "level": 2,
        "name": "Division Dungeons",
        "subtitle": "Gem Chest Quest",
        "theme": "dungeon",
        "skill_required": "3.OA.A.2",
        "skill_name": "Understanding Division",
        "unlock_requirement": "Complete Division part (3.OA.A.2) to unlock",
        "description": "Divide shimmering treasures equally into dungeon chests to unlock ancient vaults!",
    },
    {
        "id": "two_step_runner",
        "level": 3,
        "name": "Two-Step Runner",
        "subtitle": "Formula Fortress",
        "theme": "castle",
        "skill_required": "3.OA.D.8",
        "skill_name": "Two-Step Word Problems",
        "unlock_requirement": "Complete Two-Step Word Problems part (3.OA.D.8) to unlock",
        "description": "Solve dual-stage math puzzles before the goblin reaches the fortress gates!",
    },
    {
        "id": "fraction_fusion",
        "level": 4,
        "name": "Pizza Fraction Fusion",
        "subtitle": "The Master Slicer",
        "theme": "kitchen",
        "skill_required": "4.NF.A.1",
        "alt_skill_required": "4.NF.B.3",
        "skill_name": "Equivalent Fractions",
        "unlock_requirement": "Complete Fraction part (4.NF.A.1 / 4.NF.B.3) to unlock",
        "description": "Slice and fuse equivalent fractions of artisan pizza to feed hungry customers!",
    },
    {
        "id": "equation_alchemist",
        "level": 5,
        "name": "Equation Alchemist",
        "subtitle": "Cosmic Balance Scale",
        "theme": "alchemy",
        "skill_required": "6.EE.B.7",
        "alt_skill_required": "7.EE.B.4",
        "skill_name": "Solving One-Step Equations",
        "unlock_requirement": "Complete Equation part (6.EE.B.7 / 7.EE.B.4) to unlock",
        "description": "Balance the mystical alchemical scales using inverse operations to transmute elements into gold!",
    },
    {
        "id": "decimal_dash",
        "level": 6,
        "name": "Decimal Dash",
        "subtitle": "Neon Hyperlane",
        "theme": "cyber",
        "skill_required": "5.NF.B.7",
        "skill_name": "Dividing Fractions & Decimals",
        "unlock_requirement": "Complete Fraction Division part (5.NF.B.7) to unlock",
        "description": "Calculate high-speed fractional parts and division quotients to navigate through hyperlane traffic!",
    },
    {
        "id": "geometry_odyssey",
        "level": 7,
        "name": "Geometry Odyssey",
        "subtitle": "Cosmic Architect",
        "theme": "galaxy",
        "skill_required": "6.EE.A.2",
        "skill_name": "Algebraic Expressions & Formulas",
        "unlock_requirement": "Complete Algebraic Expressions part (6.EE.A.2) to unlock",
        "description": "Evaluate algebraic expressions and geometric formulas to construct celestial stations!",
    },
]

# Maximum score accepted per game session submission
MAX_SCORE_PER_GAME = int(os.getenv("MAX_SCORE_PER_GAME", "100000"))
_games_store_cache: dict[str, Any] | None = None


class GameScoreRequest(BaseModel):
    student_id: str = Field(max_length=64)
    game_id: str = Field(max_length=64)
    score: int = Field(le=1_000_000)
    stars: int = Field(default=1)
    mode: str | None = Field(default="blitz", max_length=32)
    streak_max: int | None = Field(default=0, ge=0, le=100_000)


class ResetGameScoreRequest(BaseModel):
    student_id: str
    game_id: str | None = None


def _read_games_store() -> dict[str, Any]:
    """Read games store, always under the lock to prevent race conditions across threads."""
    global _games_store_cache
    with _games_store_lock:
        if _games_store_cache is not None:
            return _games_store_cache
        if not GAMES_STORE_PATH.exists():
            _games_store_cache = {}
            return _games_store_cache
        try:
            with open(GAMES_STORE_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                _games_store_cache = loaded if isinstance(loaded, dict) else {}
                return _games_store_cache
        except Exception as e:
            logger.warning("Error reading games store from %s: %s", GAMES_STORE_PATH, e)
            _games_store_cache = {}
            return _games_store_cache


def _write_games_store(data: dict[str, Any]) -> None:
    """Write games store and invalidate the in-memory cache so the next read re-loads from disk."""
    global _games_store_cache
    try:
        tmp = GAMES_STORE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        tmp.replace(GAMES_STORE_PATH)
        _games_store_cache = None
    except Exception as e:
        logger.warning("Error writing games store to %s: %s", GAMES_STORE_PATH, e)


def _remove_student_game_records(student_id: str) -> None:
    """Remove local game records after a destructive student-data operation."""
    with _games_store_lock:
        store = _read_games_store()
        if student_id in store:
            del store[student_id]
            _write_games_store(store)


async def _get_student_game_progress(student_id: str) -> dict[str, Any]:
    store = _read_games_store()
    student_records = store.get(student_id, {})

    # 0. Attempt to hydrate from Supabase student_game_progress table if available
    try:
        supabase = get_supabase()
        db_game_res = await db_exec(
            supabase.table("student_game_progress")
            .select("game_id, high_score, stars, times_played, last_played, history")
            .eq("student_id", student_id)
        )
        if db_game_res.data:
            if student_id not in store:
                store[student_id] = {}
            for row in db_game_res.data:
                gid = row["game_id"]
                store[student_id][gid] = {
                    "high_score": row.get("high_score", 0),
                    "stars": row.get("stars", 0),
                    "times_played": row.get("times_played", 0),
                    "last_played": row.get("last_played"),
                    "history": row.get("history", []),
                }
            student_records = store[student_id]
    except Exception as e:
        logger.debug("Supabase student_game_progress sync skipped: %s", e)

    # 1. Fetch live mastery from Supabase
    mastery_map = initialize_mastery()
    try:
        supabase = get_supabase()
        res = await db_exec(
            supabase.table("student_skill_mastery")
            .select("skill_id, mastery_prob")
            .eq("student_id", student_id)
        )
        if res.data:
            for row in res.data:
                mastery_map[row["skill_id"]] = float(row["mastery_prob"])
    except Exception as e:
        logger.warning("Failed to fetch student mastery for games: %s", e)

    # 2. Check active cached session if student has active session with higher mastery
    for active_sid in get_all_active_session_ids():
        active_state = get_session(active_sid)
        if active_state and active_state.get("student_id") == student_id:
            for s_id, raw_prob in active_state.get("mastery_state", {}).items():
                try:
                    prob = float(raw_prob)
                    if prob > mastery_map.get(s_id, 0.0):
                        mastery_map[s_id] = prob
                except (ValueError, TypeError):
                    pass

    # 3. Fetch solved events for skills from session_events
    solved_skills: set[str] = set()
    try:
        supabase = get_supabase()
        events_res = await db_exec(
            supabase.table("session_events")
            .select("problem_id, is_correct")
            .eq("student_id", student_id)
            .eq("is_correct", True)
        )
        if events_res.data:
            prob_ids = [e["problem_id"] for e in events_res.data if e.get("problem_id")]
            if prob_ids:
                p_res = await db_exec(
                    supabase.table("problems").select("id, skill_id").in_("id", prob_ids)
                )
                if p_res.data:
                    for p in p_res.data:
                        if p.get("skill_id"):
                            solved_skills.add(p["skill_id"])
    except Exception as e:
        logger.warning("Failed to fetch solved problems for games progress: %s", e)

    levels_output = []
    total_stars = 0
    total_score = 0
    games_unlocked = 0
    previous_unlocked = True

    for item in GAME_LEVELS_CONFIG:
        gid = item["id"]
        req_skill = item["skill_required"]
        alt_skill = item.get("alt_skill_required")

        raw_req = mastery_map.get(req_skill)
        raw_alt = mastery_map.get(alt_skill) if alt_skill else None
        req_mastery = float(raw_req) if raw_req is not None else 0.3
        alt_mastery = float(raw_alt) if raw_alt is not None else 0.0
        effective_mastery = max(req_mastery, alt_mastery)

        skill_solved = (req_skill in solved_skills) or (bool(alt_skill) and alt_skill in solved_skills)
        skill_mastered = (effective_mastery >= 0.45) or skill_solved

        item_level = int(item["level"])
        if item_level == 1:
            is_unlocked = True
        else:
            is_unlocked = previous_unlocked and skill_mastered

        if is_unlocked:
            progress_pct = 100
        elif not previous_unlocked:
            progress_pct = 0
        else:
            progress_pct = min(95, max(15, int(((effective_mastery - 0.2) / 0.25) * 100)))

        saved_game = student_records.get(gid, {})
        high_score = saved_game.get("high_score", 0)
        stars = saved_game.get("stars", 0)

        total_stars += stars
        total_score += high_score
        if is_unlocked:
            games_unlocked += 1

        levels_output.append({
            "id": gid,
            "level": item["level"],
            "name": item["name"],
            "subtitle": item["subtitle"],
            "theme": item["theme"],
            "skill_required": req_skill,
            "skill_name": item["skill_name"],
            "unlock_requirement": item["unlock_requirement"],
            "description": item["description"],
            "is_unlocked": is_unlocked,
            "progress_percent": progress_pct,
            "high_score": high_score,
            "stars": stars,
            "times_played": saved_game.get("times_played", 0),
            "last_played": saved_game.get("last_played"),
            "history": saved_game.get("history", []),
        })

        previous_unlocked = is_unlocked

    return {
        "student_id": student_id,
        "levels": levels_output,
        "total_stars": total_stars,
        "total_score": total_score,
        "games_unlocked": games_unlocked,
        "total_games": len(GAME_LEVELS_CONFIG),
    }


@router.get("/progress")
async def get_games_progress(
    student_id: str,
    auth: dict = Depends(verify_student_access),
):
    """Retrieve persistent game unlocks, level hierarchy roadmap, high scores, and stars."""
    if not student_id or not student_id.strip():
        raise HTTPException(400, "student_id is required")
    return await _get_student_game_progress(student_id.strip())


@router.post("/score")
async def record_game_score(
    req: GameScoreRequest,
    auth: dict = Depends(verify_student_caller),
):
    """Persist a completed game score, round telemetry, and star rating permanently for the student."""
    if not req.student_id or not req.student_id.strip():
        raise HTTPException(400, "student_id is required")
    if not req.game_id or not req.game_id.strip():
        raise HTTPException(400, "game_id is required")

    clean_student_id = req.student_id.strip()
    clean_game_id = req.game_id.strip()

    if auth.get("role") != "student":
        raise HTTPException(
            status_code=403,
            detail="Student authentication required",
        )

    if auth.get("sub") != clean_student_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot modify another student's game state",
        )

    valid_game_ids = {item["id"] for item in GAME_LEVELS_CONFIG}
    if clean_game_id not in valid_game_ids:
        raise HTTPException(400, f"Invalid game_id '{clean_game_id}'. Allowed: {sorted(valid_game_ids)}")
    progress = await _get_student_game_progress(clean_student_id)
    selected_level = next(level for level in progress["levels"] if level["id"] == clean_game_id)
    if not selected_level["is_unlocked"]:
        raise HTTPException(403, "This game level is still locked. Complete the required curriculum first.")
    if req.score < 0:
        raise HTTPException(400, "Score must be non-negative")
    if req.score > MAX_SCORE_PER_GAME:
        raise HTTPException(422, f"Score {req.score} exceeds the maximum allowed per session ({MAX_SCORE_PER_GAME:,}).")
    if req.stars not in (1, 2, 3):
        raise HTTPException(400, "Stars must be between 1 and 3 (allowed: 1, 2, 3)")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with _games_store_lock:
        _games_store_cache_inner: dict[str, Any] | None = None
        if GAMES_STORE_PATH.exists():
            try:
                with open(GAMES_STORE_PATH, "r", encoding="utf-8") as _f:
                    _loaded = json.load(_f)
                    _games_store_cache_inner = _loaded if isinstance(_loaded, dict) else {}
            except Exception:
                pass
        store: dict[str, Any] = _games_store_cache_inner or {}

        student_record = store.setdefault(clean_student_id, {})
        game_record = student_record.setdefault(clean_game_id, {
            "high_score": 0,
            "stars": 0,
            "times_played": 0,
            "last_played": None,
            "history": [],
        })

        game_record["times_played"] = game_record.get("times_played", 0) + 1
        game_record["last_played"] = now_iso
        if req.score > game_record.get("high_score", 0):
            game_record["high_score"] = req.score
        if req.stars > game_record.get("stars", 0):
            game_record["stars"] = min(3, max(1, req.stars))

        history_list = game_record.setdefault("history", [])
        history_list.append({
            "score": req.score,
            "stars": req.stars,
            "mode": req.mode or "blitz",
            "streak_max": req.streak_max or 0,
            "timestamp": now_iso,
        })
        if len(history_list) > 20:
            history_list.pop(0)

        _write_games_store(store)

    # Dual-write write-through to Supabase student_game_progress table
    try:
        supabase = get_supabase()
        await db_exec(
            supabase.table("student_game_progress").upsert({
                "student_id": clean_student_id,
                "game_id": clean_game_id,
                "high_score": game_record["high_score"],
                "stars": game_record["stars"],
                "times_played": game_record["times_played"],
                "last_played": game_record["last_played"],
                "history": game_record["history"],
                "updated_at": now_iso,
            }, on_conflict="student_id,game_id")
        )
    except Exception as e:
        logger.debug("Supabase student_game_progress write-through skipped: %s", e)

    return await _get_student_game_progress(clean_student_id)


@router.post("/reset")
async def reset_game_score(
    req: ResetGameScoreRequest,
    auth: dict = Depends(verify_student_caller),
):
    """Reset high scores and stats for a specific game or all games for a student."""
    if not req.student_id or not req.student_id.strip():
        raise HTTPException(400, "student_id is required")

    clean_student_id = req.student_id.strip()

    if auth.get("role") != "student":
        raise HTTPException(
            status_code=403,
            detail="Student authentication required",
        )

    if auth.get("sub") != clean_student_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot modify another student's game state",
        )

    if req.game_id and req.game_id.strip():
        valid_game_ids = {item["id"] for item in GAME_LEVELS_CONFIG}
        if req.game_id.strip() not in valid_game_ids:
            raise HTTPException(400, f"Invalid game_id '{req.game_id}'. Allowed: {sorted(valid_game_ids)}")

    with _games_store_lock:
        store = _read_games_store()

        if clean_student_id in store:
            if req.game_id and req.game_id.strip():
                clean_game_id = req.game_id.strip()
                if clean_game_id in store[clean_student_id]:
                    store[clean_student_id][clean_game_id] = {
                        "high_score": 0,
                        "stars": 0,
                        "times_played": 0,
                        "last_played": None,
                        "history": [],
                    }
            else:
                store[clean_student_id] = {
                    item["id"]: {
                        "high_score": 0,
                        "stars": 0,
                        "times_played": 0,
                        "last_played": None,
                        "history": [],
                    }
                    for item in GAME_LEVELS_CONFIG
                }
            _write_games_store(store)

    # Synchronize reset with Supabase student_game_progress
    try:
        supabase = get_supabase()
        if req.game_id and req.game_id.strip():
            await db_exec(
                supabase.table("student_game_progress")
                .delete()
                .eq("student_id", clean_student_id)
                .eq("game_id", req.game_id.strip())
            )
        else:
            await db_exec(
                supabase.table("student_game_progress")
                .delete()
                .eq("student_id", clean_student_id)
            )
    except Exception as e:
        logger.debug("Supabase student_game_progress reset sync skipped: %s", e)

    return await _get_student_game_progress(clean_student_id)
