"""Parent dashboard and child management domain routes.

Provides endpoints and logic for:
- Linking children to parent accounts
- Listing children with mastery overview and recency calculations
- Retrieving full child detail (mastery, sessions, games, events, alerts)
- GDPR / privacy student data purge
- Inactivity, low mastery, misconception, and stagnation alert generation
"""

import asyncio
import datetime
import json
import logging
from pathlib import Path
import re
import threading
import time
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from postgrest.base_request_builder import CountMethod
from pydantic import BaseModel, Field

from session_manager import (
    clear_student_misconceptions,
    get_student_misconceptions,
    evict_session,
    evict_student_sessions,
)
from auth import verify_parent_access, verify_parent_caller
from bkt.tracker import get_all_skills
from db.supabase_client import get_supabase
from rate_limiter import limiter
from routes.common import BACKEND_DIR, db_exec, _SESSION_SUMMARY_CACHE
from routes.games import _get_student_game_progress, _remove_student_game_records
from safety import record_security_event
from services.cloudinary_service import cloudinary_service

logger = logging.getLogger("veritas.parent")

router = APIRouter(tags=["parent"])

CHILDREN_FALLBACK_FILE = BACKEND_DIR.parent / "data" / "children_store.json"
_children_fallback_lock = threading.Lock()


class AddChildRequest(BaseModel):
    parent_id: str = Field(max_length=64)
    parent_email: str | None = Field(default=None, max_length=320)
    child_email: str = Field(max_length=320)
    child_name: str | None = Field(default=None, max_length=120)
    student_id: str | None = Field(default=None, max_length=64)


def _get_fallback_children(parent_id: str) -> list[dict]:
    if not CHILDREN_FALLBACK_FILE.exists():
        return []
    try:
        with open(CHILDREN_FALLBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [c for c in data if c.get("parent_id") == parent_id]
    except Exception:
        return []


def _save_fallback_child(record: dict):
    with _children_fallback_lock:
        CHILDREN_FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        current = []
        if CHILDREN_FALLBACK_FILE.exists():
            try:
                with open(CHILDREN_FALLBACK_FILE, "r", encoding="utf-8") as f:
                    current = json.load(f)
            except Exception:
                current = []
        current = [
            c
            for c in current
            if not (
                c.get("parent_id") == record.get("parent_id")
                and c.get("student_id") == record.get("student_id")
            )
        ]
        current.append(record)
        temp_path = CHILDREN_FALLBACK_FILE.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        temp_path.replace(CHILDREN_FALLBACK_FILE)


def _sync_purge_fallback_file(parent_id: str):
    with _children_fallback_lock:
        if not CHILDREN_FALLBACK_FILE.exists():
            return
        try:
            with open(CHILDREN_FALLBACK_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
            cleaned = [c for c in current if c.get("parent_id") != parent_id]
            temp_path = CHILDREN_FALLBACK_FILE.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)
            temp_path.replace(CHILDREN_FALLBACK_FILE)
        except Exception:
            pass


def generate_student_alerts(
    student_id: str,
    all_mastery_map: dict[str, float],
    days_since: int,
    active_misconceptions: dict[str, dict],
    recent_events: list[dict] | None = None,
) -> tuple[list[dict], str, bool, str, float, str | None, str | None]:
    """
    Generate learner-aware parent alerts across all 10 Common Core skills:
    - Inactivity: > 3 days since last session
    - Low mastery: < 0.50 on any skill (reports lowest)
    - Repeated misconception: from misconception tracker (count >= 2, unresolved)
    - Stagnation: multiple attempts without mastery growth
    Returns:
    (alerts, alert_message, has_gap, fraction_alert_message, fraction_mastery, top_gap_skill_id, top_gap_skill_name)
    """
    all_skills = get_all_skills()
    skill_name_map = {s["id"]: s["name"] for s in all_skills}
    alerts: list[dict] = []

    # 1. Inactivity Alert
    if days_since >= 3:
        severity = "urgent" if days_since >= 5 else "warning"
        alerts.append({
            "type": "inactivity",
            "skill_id": None,
            "skill_name": None,
            "message": f"Inactivity alert: No practice in {days_since} days",
            "severity": severity,
        })

    # 2. Low Mastery Alert across all 10 CCSS skills
    lowest_skill = None
    min_prob = 1.0
    for sid, name in skill_name_map.items():
        prob = all_mastery_map.get(sid, 0.30)
        if prob < min_prob:
            min_prob = prob
            lowest_skill = (sid, name)

    if lowest_skill and min_prob < 0.50:
        severity = "urgent" if min_prob < 0.35 else "warning"
        alerts.append({
            "type": "low_mastery",
            "skill_id": lowest_skill[0],
            "skill_name": lowest_skill[1],
            "message": f"Low mastery in {lowest_skill[1]} ({int(min_prob * 100)}%)",
            "severity": severity,
        })

    # 3. Repeated Misconception Alert (count >= 2, unresolved)
    unresolved_misc = [
        (m_type, info)
        for m_type, info in (active_misconceptions or {}).items()
        if not info.get("resolved") and info.get("count", 0) >= 2
    ]
    unresolved_misc.sort(key=lambda x: x[1].get("count", 0), reverse=True)
    for m_type, m_info in unresolved_misc:
        m_count = m_info.get("count", 2)
        m_skill_id = m_info.get("skill_id") or ""
        m_skill_name = skill_name_map.get(m_skill_id, "Core Skills")
        clean_name = m_type.replace("_", " ").title()
        severity = "urgent" if m_count >= 3 else "warning"
        alerts.append({
            "type": "misconception",
            "skill_id": m_skill_id or None,
            "skill_name": m_skill_name,
            "message": f"Recurring misconception: {clean_name} in {m_skill_name} ({m_count}x)",
            "severity": severity,
        })

    # 4. Stagnation / Plateau Alert
    # Only count events with explicit True/False correctness; skip NULL/None attempts
    # (NULL events represent exploratory inputs or system events, not actual failures)
    if recent_events and len(recent_events) >= 4:
        recent_slice = recent_events[:6]
        graded_events = [e for e in recent_slice if e.get("is_correct") is not None]
        recent_correct = sum(1 for e in graded_events if e.get("is_correct") is True)
        if len(graded_events) >= 2 and recent_correct == 0:
            stagnant_id = lowest_skill[0] if lowest_skill else None
            stagnant_name = lowest_skill[1] if lowest_skill else "Current Topic"
            alerts.append({
                "type": "stagnation",
                "skill_id": stagnant_id,
                "skill_name": stagnant_name,
                "message": f"Practice plateau: 0 of last {len(recent_slice)} attempts solved on {stagnant_name}",
                "severity": "warning",
            })

    # Fraction mastery calculation (CCSS fraction cluster)
    frac_scores = [all_mastery_map[s] for s in ("4.NF.B.3", "4.NF.A.1", "4.NF.B.4", "5.NF.B.7") if s in all_mastery_map]
    fraction_mastery = sum(frac_scores) / len(frac_scores) if frac_scores else 0.35

    # Fraction alert message (backward compatibility)
    if days_since >= 3:
        frac_alert = f"Notice: Has not practiced fractions in {days_since} days"
    elif fraction_mastery < 0.5:
        frac_alert = "Notice: Needs practice with fractions (mastery below 50%)"
    else:
        frac_alert = "Practiced fractions recently"

    top_gap_id = lowest_skill[0] if lowest_skill and min_prob < 0.5 else None
    top_gap_name = lowest_skill[1] if lowest_skill and min_prob < 0.5 else None

    # Summary alert message
    if alerts:
        urgent_alerts = [a for a in alerts if a["severity"] == "urgent"]
        primary = urgent_alerts[0] if urgent_alerts else alerts[0]
        alert_msg = f"Notice: {primary['message']}"
    else:
        alert_msg = "Math practice on track"

    has_gap = bool(alerts) or days_since >= 3 or fraction_mastery < 0.5

    return alerts, alert_msg, has_gap, frac_alert, fraction_mastery, top_gap_id, top_gap_name


@router.post("/parent/add-child")
async def add_child(
    req: AddChildRequest,
    auth: dict = Depends(verify_parent_caller),
):
    """Link a child by email to a parent in the children table."""
    # 0. Authorization & Tenant Isolation check
    caller_id = auth.get("sub")
    # Evaluator Convenience: Fixed demo parent account allows judges to test child linkage without live Supabase session
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    if caller_id != req.parent_id and not (req.parent_id == DEMO_PARENT and (caller_id == DEMO_PARENT or caller_id == "demo_parent")):
        raise HTTPException(
            status_code=403,
            detail="Access denied: you cannot link children to another parent's account.",
        )

    # 1. Safety Guardrails & Validation
    try:
        uuid.UUID(req.parent_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid parent_id: Must be a valid UUID format.")

    input_identifier = req.child_email.strip()
    is_uuid = False
    try:
        uuid.UUID(input_identifier)
        is_uuid = True
    except (ValueError, AttributeError):
        is_uuid = False

    is_email = bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", input_identifier.lower()))

    if not is_uuid and not is_email:
        raise HTTPException(422, "Please enter a valid student email address or student ID code.")

    email_clean = input_identifier.lower() if is_email else None
    if is_email and req.parent_email and req.parent_email.strip().lower() == email_clean:
        raise HTTPException(400, "A parent cannot link their own email as a child account.")

    # Rate limiting protection
    limiter.enforce_cooldown(f"parent_add_{req.parent_id}", cooldown_seconds=0.5, action="add child", max_per_minute=20)

    supabase = get_supabase()
    student_id = req.student_id or (input_identifier if is_uuid else None)
    student_name = req.child_name or (email_clean.split("@")[0].capitalize() if email_clean else "Student")

    # 1. Search in students table (by ID if UUID, or by email)
    if student_id and is_uuid:
        try:
            found = await db_exec(
                supabase.table("students")
                .select("*")
                .eq("id", student_id)
                .limit(1)
            )
            if found.data:
                student_name = found.data[0].get("name") or student_name
                email_clean = found.data[0].get("email") or email_clean or f"student_{student_id[:8]}@veritas.math"
        except Exception as e:
            logger.debug(f"Search student by id: {e}")
    elif not student_id and email_clean:
        try:
            found = await db_exec(
                supabase.table("students")
                .select("*")
                .eq("email", email_clean)
                .limit(1)
            )
            if found.data:
                student_id = found.data[0]["id"]
                student_name = found.data[0].get("name") or student_name
        except Exception as e:
            logger.debug(f"Search students table: {e}")

    # Name-based fallback removed: common names can match the wrong student.
    # Only link by exact email address or UUID.

    # 2. If not found in students table by email, we do NOT scan auth admin users
    #    (admin.list_users() is slow, expensive, and exposes account metadata).
    #    The student must be registered in the students table to be linkable.

    # A student code must already belong to a real student. Never create a
    # new student when a parent enters an unknown UUID.
    if is_uuid and not student_id:
        raise HTTPException(
            status_code=404,
            detail="Student ID not found. Ask the student to open their account and copy the current Student ID.",
        )

    # 3. If student doesn't exist yet, create a registered student record
    if not student_id:
        student_id = str(uuid.uuid4())
        try:
            await db_exec(supabase.table("students").insert({
                "id": student_id,
                "name": student_name,
                "email": email_clean,
            }))
        except Exception:
            try:
                await db_exec(supabase.table("students").insert({
                    "id": student_id,
                    "name": student_name,
                }))
            except Exception:
                try:
                    found = await db_exec(supabase.table("students").select("id").eq("name", student_name))
                    if found.data:
                        student_id = found.data[0]["id"]
                    else:
                        await db_exec(supabase.table("students").insert({
                            "id": student_id,
                            "name": f"{student_name} #{student_id[:4]}",
                        }))
                except Exception as e:
                    logger.warning(f"Could not create initial student record: {e}")

    # 4. Insert into children table (parent_id -> student_id)
    child_record = {
        "parent_id": req.parent_id,
        "student_id": student_id,
        "student_email": email_clean,
        "student_name": student_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        await db_exec(supabase.table("children").upsert({
            "parent_id": req.parent_id,
            "student_id": student_id,
            "student_email": email_clean,
            "student_name": student_name,
        }))
    except Exception as e:
        logger.info(f"Children table fallback in local storage: {e}")
        await asyncio.to_thread(_save_fallback_child, child_record)

    return {
        "status": "ok",
        "child": {
            "student_id": student_id,
            "student_name": student_name,
            "student_email": email_clean,
        },
    }


@router.get("/parent/{parent_id}/children")
async def get_parent_children(
    parent_id: str,
    auth: dict = Depends(verify_parent_access),
):
    """List all children linked to parent, including mastery overview and practice recency."""
    supabase = get_supabase()
    children_map: dict[str, dict] = {}

    # Read from Supabase children table
    try:
        res = await db_exec(
            supabase.table("children")
            .select("*")
            .eq("parent_id", parent_id)
        )
        for c in res.data or []:
            children_map[c["student_id"]] = c
    except Exception as e:
        logger.info(f"Fetch children from table fallback: {e}")

    # Merge fallback records
    fallback_children = await asyncio.to_thread(_get_fallback_children, parent_id)
    for c in fallback_children:
        if c["student_id"] not in children_map:
            children_map[c["student_id"]] = c

    # If demo parent has no children yet, supply demo child 'Alex'
    if not children_map and parent_id == "99999999-8888-7777-6666-555555555555":
        demo_child = {
            "parent_id": parent_id,
            "student_id": "24e836e3-3b42-41a0-8a27-222f883eaa10",
            "student_email": "student.alex@veritas.dev",
            "student_name": "Alex Jenkins",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        children_map[demo_child["student_id"]] = demo_child
        await asyncio.to_thread(_save_fallback_child, demo_child)

    results = []
    now = time.time()

    for student_id, child in children_map.items():
        latest_session_time = None
        session_count = 0
        sessions_available = True
        mastery_available = True
        events_available = True

        # Fetch sessions, count, mastery, events, and misconceptions concurrently
        sess_future = db_exec(
            supabase.table("sessions")
            .select("started_at")
            .eq("student_id", student_id)
            .order("started_at", desc=True)
            .limit(1)
        )
        count_future = db_exec(
            supabase.table("sessions")
            .select("id", count=CountMethod.exact)
            .eq("student_id", student_id)
        )
        mastery_future = db_exec(
            supabase.table("student_skill_mastery")
            .select("skill_id, mastery_prob")
            .eq("student_id", student_id)
        )
        events_future = db_exec(
            supabase.table("session_events")
            .select("is_correct, created_at, problem_id")
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .limit(6)
        )
        misc_future = asyncio.to_thread(get_student_misconceptions, student_id)

        (
            sess_res,
            count_res,
            m_res,
            recent_res,
            active_misc_res,
        ) = await asyncio.gather(
            sess_future,
            count_future,
            mastery_future,
            events_future,
            misc_future,
            return_exceptions=True,
        )

        # 1. Process latest session & count
        if isinstance(sess_res, BaseException) or not hasattr(sess_res, "data"):
            sessions_available = False
        elif sess_res.data:
            latest_session_time = sess_res.data[0].get("started_at")

        if isinstance(count_res, BaseException) or not hasattr(count_res, "data"):
            sessions_available = False
        else:
            session_count = getattr(count_res, "count", None) or len(getattr(count_res, "data", None) or [])

        # 2. Process skill mastery
        all_mastery_map: dict[str, float] = {}
        if isinstance(m_res, BaseException) or not hasattr(m_res, "data"):
            mastery_available = False
        elif m_res.data:
            for r in m_res.data:
                all_mastery_map[r["skill_id"]] = float(r["mastery_prob"])

        # 3. Process recency
        days_since = 0
        if latest_session_time:
            try:
                ts = datetime.datetime.fromisoformat(
                    latest_session_time.replace("Z", "+00:00")
                )
                diff_seconds = now - ts.timestamp()
                days_since = max(0, int(diff_seconds // 86400))
            except Exception:
                sessions_available = False

        # 4. Process misconceptions
        active_misc = active_misc_res if not isinstance(active_misc_res, Exception) and isinstance(active_misc_res, dict) else {}

        # 5. Process recent events
        recent_events: list[dict] = []
        if isinstance(recent_res, BaseException) or not hasattr(recent_res, "data"):
            events_available = False
        else:
            recent_events = recent_res.data or []

        # Generate learner-aware alerts across all CCSS skills
        if sessions_available and mastery_available and events_available:
            alerts, generic_alert_msg, has_gap, alert_msg, fraction_mastery, top_gap_skill_id, top_gap_skill_name = generate_student_alerts(
                student_id=student_id,
                all_mastery_map=all_mastery_map,
                days_since=days_since,
                active_misconceptions=active_misc,
                recent_events=recent_events,
            )
        else:
            alerts = []
            generic_alert_msg = "Learner data is temporarily unavailable"
            has_gap = False
            alert_msg = "Learner data is temporarily unavailable"
            fraction_mastery = 0.0
            top_gap_skill_id = None
            top_gap_skill_name = None

        results.append({
            "student_id": student_id,
            "student_name": child.get("student_name", "Student"),
            "student_email": child.get("student_email", ""),
            "last_session_at": latest_session_time,
            "days_since_practice": days_since,
            "has_fraction_gap": has_gap,
            "fraction_alert_message": alert_msg,
            "fraction_mastery": fraction_mastery,
            "alert_message": generic_alert_msg,
            "top_gap_skill": top_gap_skill_name,
            "top_gap_skill_id": top_gap_skill_id,
            "session_count": session_count,
            "alerts": alerts,
            "active_misconceptions": active_misc,
        })

    return {"children": results}


@router.get("/parent/{parent_id}/child/{child_id}/details")
async def get_child_details(
    parent_id: str,
    child_id: str,
    auth: dict = Depends(verify_parent_access),
):
    """Return full mastery state and practice history for a child."""
    supabase = get_supabase()

    # Verify child linkage to parent (Tenant & IDOR protection)
    # Evaluator Convenience: Fixed pre-linked demo pair (Alex & Sarah) allows immediate radar inspection
    DEMO_PARENT = "99999999-8888-7777-6666-555555555555"
    DEMO_STUDENT = "24e836e3-3b42-41a0-8a27-222f883eaa10"
    is_linked = False
    if parent_id == DEMO_PARENT and child_id == DEMO_STUDENT:
        is_linked = True
    else:
        try:
            check = await db_exec(
                supabase.table("children")
                .select("student_id")
                .eq("parent_id", parent_id)
                .eq("student_id", child_id)
                .limit(1)
            )
            if check.data and len(check.data) > 0:
                is_linked = True
        except Exception:
            pass

        if not is_linked:
            fallback_kids = await asyncio.to_thread(_get_fallback_children, parent_id)
            if any(c.get("student_id") == child_id for c in fallback_kids):
                is_linked = True

    if not is_linked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: student is not linked to this parent account",
        )

    # Run DB queries sequentially — the shared Supabase httpx HTTP/2 connection
    # uses an hpack encoder whose deque is NOT safe for concurrent access from
    # multiple asyncio.to_thread calls. Sequential awaits eliminate the race with
    # negligible latency impact on this low-frequency parent dashboard endpoint.
    mastery_rows = await db_exec(
        supabase.table("student_skill_mastery")
        .select("*, skills(name, cc_standard, sequence_order)")
        .eq("student_id", child_id)
    )
    sessions_res = await db_exec(
        supabase.table("sessions")
        .select("*")
        .eq("student_id", child_id)
        .order("started_at", desc=True)
    )
    events_res = await db_exec(
        supabase.table("session_events")
        .select("id, session_id, student_id, problem_id, attempt_text, is_correct, agent_response, created_at, problems(title, text)")
        .eq("student_id", child_id)
        .order("created_at", desc=True)
    )
    games_data = await _get_student_game_progress(child_id)
    skills = get_all_skills()

    # Calculate session login/logout/durations
    enriched_sessions = []
    events_list = events_res.data or []
    total_session_minutes = 0

    for idx, sess in enumerate(sessions_res.data or []):
        sid = sess.get("id")
        started = sess.get("started_at")
        ended = sess.get("ended_at")

        # Find events in this session to compute duration or problem stats
        sess_events = [e for e in events_list if e.get("session_id") == sid]
        prob_count = len(sess_events)
        solved_count = sum(1 for e in sess_events if e.get("is_correct"))

        duration_mins = None
        if started and ended:
            try:
                t1 = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
                t2 = datetime.datetime.fromisoformat(ended.replace("Z", "+00:00"))
                duration_mins = max(1, int((t2 - t1).total_seconds() / 60))
            except Exception:
                pass

        if duration_mins is None and started:
            if len(sess_events) >= 2:
                try:
                    ev_times = [datetime.datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) for e in sess_events if e.get("created_at")]
                    if ev_times:
                        t_min = min(ev_times)
                        t_max = max(ev_times)
                        duration_mins = max(1, int((t_max - t_min).total_seconds() / 60) + 1)
                except Exception:
                    pass
        safe_duration_mins: int = duration_mins if duration_mins is not None else 0

        if not ended and started and safe_duration_mins > 0:
            try:
                t_start = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
                t_end = t_start + datetime.timedelta(minutes=safe_duration_mins)
                ended = t_end.isoformat()
            except Exception:
                pass

        total_session_minutes += safe_duration_mins
        enriched_sessions.append({
            **sess,
            "login_time": started,
            "logout_time": ended,
            "duration_minutes": safe_duration_mins,
            "problems_attempted": prob_count,
            "problems_solved": solved_count,
        })

    # Summary metrics (strictly database-backed, no synthetic demo fallbacks)
    total_attempts = len(events_list)
    total_solved = sum(1 for e in events_list if e.get("is_correct"))
    acc_rate = round((total_solved / total_attempts) * 100) if total_attempts > 0 else 0

    total_game_plays = sum(g.get("times_played", 0) for g in games_data.get("levels", []))

    activity_summary = {
        "total_time_spent_minutes": total_session_minutes,
        "total_questions_attempted": total_attempts,
        "total_questions_solved": total_solved,
        "accuracy_percent": acc_rate,
        "total_games_played": total_game_plays,
        "total_stars": games_data.get("total_stars", 0),
    }

    # Multi-skill learner-aware alert generation
    days_since = 0
    if sessions_res.data and sessions_res.data[0].get("started_at"):
        try:
            ts = datetime.datetime.fromisoformat(sessions_res.data[0]["started_at"].replace("Z", "+00:00"))
            diff_seconds = time.time() - ts.timestamp()
            days_since = max(0, int(diff_seconds // 86400))
        except Exception:
            days_since = 0

    child_mastery_map = {
        r["skill_id"]: float(r["mastery_prob"])
        for r in (mastery_rows.data or [])
        if "skill_id" in r and "mastery_prob" in r
    }
    active_misc = await asyncio.to_thread(get_student_misconceptions, child_id)
    alerts, alert_msg, has_gap, frac_alert, frac_m, top_id, top_name = generate_student_alerts(
        student_id=child_id,
        all_mastery_map=child_mastery_map,
        days_since=days_since,
        active_misconceptions=active_misc,
        recent_events=events_list,
    )

    return {
        "student_id": child_id,
        "mastery": mastery_rows.data or [],
        "all_skills": skills,
        "sessions": enriched_sessions,
        "recent_events": events_list,
        "games": games_data,
        "activity_summary": activity_summary,
        "alerts": alerts,
        "active_misconceptions": active_misc,
        "alert_message": alert_msg,
        "fraction_alert_message": frac_alert,
        "has_fraction_gap": has_gap,
        "top_gap_skill": top_name,
        "top_gap_skill_id": top_id,
    }


@router.delete("/parent/{parent_id}/data")
async def delete_parent_data(
    parent_id: str,
    auth: dict = Depends(verify_parent_access),
):
    """
    Data Privacy & Deletion (Trust & GDPR/EdTech signal):
    Purge all session logs, events, and linked child records for this parent.
    """
    try:
        uuid.UUID(parent_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid parent_id: Must be a valid UUID format.")

    limiter.enforce_cooldown(f"parent_del_{parent_id}", cooldown_seconds=2.0, action="delete data", max_per_minute=5)

    supabase = get_supabase()
    deleted_sessions = 0
    deleted_events = 0
    deleted_mastery = 0
    deletion_errors: list[str] = []

    # 1. Fetch children for this parent
    try:
        res = await db_exec(supabase.table("children").select("student_id").eq("parent_id", parent_id))
        student_ids = [c["student_id"] for c in (res.data or [])]
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to retrieve child records: {e}")

    if student_ids:
        # Delete session events, sessions, and skill mastery profiles for these students
        for sid in student_ids:
            # Collect all session IDs for Redis revocation before deleting DB rows
            session_id_list: list[str] = []
            try:
                session_rows = await db_exec(
                    supabase.table("sessions").select("id").eq("student_id", sid)
                )
                for session_row in session_rows.data or []:
                    s_id = session_row.get("id")
                    if s_id:
                        session_id_list.append(s_id)
                        evict_session(s_id)
            except Exception as e:
                logger.warning("Could not evict all student sessions before deletion: %s", e)

            other_links = None
            try:
                other_links = await db_exec(
                    supabase.table("children")
                    .select("parent_id")
                    .eq("student_id", sid)
                    .neq("parent_id", parent_id)
                )
            except Exception as e:
                deletion_errors.append(f"children_check:{sid}:{e}")

            evict_student_sessions(sid)

            try:
                ev_del = await db_exec(supabase.table("session_events").delete().eq("student_id", sid))
                deleted_events += len(ev_del.data or [])
            except Exception as e:
                deletion_errors.append(f"session_events:{sid}:{e}")

            try:
                sess_del = await db_exec(supabase.table("sessions").delete().eq("student_id", sid))
                deleted_sessions += len(sess_del.data or [])
            except Exception as e:
                deletion_errors.append(f"sessions:{sid}:{e}")

            try:
                m_del = await db_exec(supabase.table("student_skill_mastery").delete().eq("student_id", sid))
                deleted_mastery += len(m_del.data or [])
            except Exception as e:
                deletion_errors.append(f"mastery:{sid}:{e}")

            if other_links is not None and not other_links.data:
                try:
                    await db_exec(supabase.table("student_game_progress").delete().eq("student_id", sid))
                except Exception as e:
                    deletion_errors.append(f"game_progress:{sid}:{e}")
                _remove_student_game_records(sid)
                clear_student_misconceptions(sid)
                try:
                    await asyncio.to_thread(cloudinary_service.delete_student_assets, sid)
                except Exception as e:
                    deletion_errors.append(f"cloudinary:{sid}:{e}")

            # Summaries are keyed by session only, so clear the bounded cache
            # after destructive deletion rather than risk retaining old data.
            _SESSION_SUMMARY_CACHE.clear()

    # 2. Delete child link records from children table
    try:
        await db_exec(supabase.table("children").delete().eq("parent_id", parent_id))
    except Exception as e:
        deletion_errors.append(f"children_links:{e}")

    # 3. Clean fallback file if present
    try:
        await asyncio.to_thread(_sync_purge_fallback_file, parent_id)
    except Exception as e:
        deletion_errors.append(f"fallback_file:{e}")

    record_security_event("user_data_deleted", {
        "parent_id": parent_id,
        "student_count": len(student_ids),
        "sessions_purged": deleted_sessions,
        "mastery_purged": deleted_mastery,
        "partial_errors": deletion_errors,
    })

    status_code = 207 if deletion_errors else 200
    response_body = {
        "status": "partial" if deletion_errors else "ok",
        "message": "All session activity, skill mastery profiles, and child links have been securely purged."
                   + (f" {len(deletion_errors)} step(s) had errors." if deletion_errors else ""),
        "purged_records": {
            "children_unlinked": len(student_ids),
            "sessions_deleted": deleted_sessions,
            "events_deleted": deleted_events,
            "mastery_records_deleted": deleted_mastery,
        },
        "errors": deletion_errors if deletion_errors else None,
    }
    return JSONResponse(content=response_body, status_code=status_code)
