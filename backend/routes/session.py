"""
Tutoring Session endpoints: start, reset, message stream, next problem, and work upload.
"""
import uuid
import json
import asyncio
import datetime
from typing import Any, AsyncGenerator, Optional
from fastapi import APIRouter, HTTPException, Depends, Header, Request, UploadFile, File, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from graph.orchestrator import TutorState
from agents.content_agent import get_next_problem
from agents.diagnostic_agent import run_diagnostic_agent
from bkt.tracker import initialize_mastery, get_next_skill, update_mastery
from db.supabase_client import get_supabase
from auth import (
    create_session_token,
    verify_session_token,
    verify_session_access,
    verify_student_caller,
    revoke_session_token,
)
from rate_limiter import limiter
from safety import (
    sanitize_input,
    check_prompt_injection,
    check_harmful_content,
    validate_image_upload,
    record_security_event,
    SOCRATIC_BOUNDARY_RESPONSE,
)
from session_manager import (
    get_session,
    save_session,
    evict_session,
    evict_student_sessions,
    record_session_event,
    get_session_lock,
    get_student_misconceptions,
    save_student_misconception,
    resolve_student_misconceptions_for_skill,
    clear_student_misconceptions,
)
from services.cloudinary_service import cloudinary_service
from routes.common import (
    db_exec,
    SSE_HEADERS,
    DEMO_STUDENT_ID,
    get_orchestrator_graph,
    _public_problem,
    _SESSION_SUMMARY_CACHE,
    logger,
)

router = APIRouter(prefix="/session", tags=["Tutoring Sessions"])


# ── Pydantic Request Models ──────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    student_name: str = Field(min_length=1, max_length=120)
    student_id: str | None = Field(default=None, max_length=64)
    student_email: str | None = Field(default=None, max_length=320)


class ResetSessionRequest(BaseModel):
    student_id: str
    session_id: str | None = None


class MessageRequest(BaseModel):
    session_id: str = Field(max_length=64)
    message: str = Field(min_length=1, max_length=4000)


class NextProblemRequest(BaseModel):
    session_id: str
    mark_previous_correct: bool = False


# ── Internal Helpers ─────────────────────────────────────────────────────────

async def _update_mastery_for_skill(session_state: dict, skill_id: str, attempt_type: str = "independent_attempt") -> None:
    """Update BKT mastery for a solved skill and persist to Supabase. Safe to call from any async route."""
    if not skill_id:
        return
    if session_state.get("current_problem_credited", False):
        logger.info(
            "Skill %s already credited for current problem in session %s, skipping duplicate update.",
            skill_id,
            session_state.get("session_id"),
        )
        return

    raw_old = session_state.get("mastery_state", {}).get(skill_id)
    old_m = float(raw_old) if raw_old is not None else 0.3
    new_m = update_mastery(old_m, True, skill_id, attempt_type=attempt_type)
    # Persist to DB BEFORE committing in-memory mutation so we can roll back on failure
    try:
        supabase = get_supabase()
        await asyncio.to_thread(
            lambda: supabase.table("student_skill_mastery").upsert({
                "student_id": session_state["student_id"],
                "skill_id": skill_id,
                "mastery_prob": round(new_m, 4),
            }, on_conflict="student_id,skill_id").execute()
        )
        # Commit in-memory state only after successful DB write
        session_state["current_problem_credited"] = True
        session_state.setdefault("mastery_state", {})[skill_id] = round(new_m, 4)
        # Invalidate stale session summary so the parent dashboard reflects the new mastery
        _SESSION_SUMMARY_CACHE.pop(session_state.get("session_id", ""), None)
    except Exception as e:
        logger.warning("Failed to persist updated mastery to Supabase; in-memory state NOT mutated: %s", e)


# ── Route Handlers ───────────────────────────────────────────────────────────

@router.post("/start")
async def start_session(
    req: StartSessionRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
):
    """Create a new tutoring session, issue a scoped session token, and return the first problem."""
    auth_identity = (req.student_email.strip().lower() if req.student_email else None) or (req.student_id.strip() if req.student_id else None)
    requester = request.client.host if request.client else "unknown"
    auth_key = auth_identity or f"anon_{requester}"
    limiter.enforce_auth_rate_limit(auth_key, max_attempts=10, window_seconds=60.0)
    limiter.enforce_auth_rate_limit(
        f"session_start_ip_{requester}",
        max_attempts=30,
        window_seconds=60.0,
    )

    supabase = get_supabase()

    token = None
    if authorization:
        parts = authorization.strip().split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else (parts[0] if parts else None)
    elif x_session_token:
        token = x_session_token.strip()

    authenticated_sub = None
    if token:
        try:
            payload = verify_session_token(token)
        except HTTPException as e:
            raise HTTPException(
                status_code=e.status_code or 401,
                detail=e.detail or "Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if payload.get("role") != "student":
            raise HTTPException(
                status_code=403,
                detail="Student account required for tutoring sessions",
            )
        authenticated_sub = payload.get("sub")

    student_id = None
    clean_req_student_id = req.student_id.strip() if req.student_id and req.student_id.strip() else None

    # Flow A: Authenticated user
    if authenticated_sub:
        student_id = authenticated_sub
        try:
            upsert_payload = {"id": student_id, "name": req.student_name}
            if req.student_email:
                upsert_payload["email"] = req.student_email.strip().lower()
            await db_exec(supabase.table("students").upsert(upsert_payload))
        except Exception as e:
            print(f"[WARN] Authenticated student upsert fallback: {e}")

    # Flow B: Explicit student_id without auth token
    elif clean_req_student_id:
        try:
            uuid.UUID(clean_req_student_id)
        except (ValueError, AttributeError):
            raise HTTPException(422, "Invalid student_id: Must be a valid UUID format.")

        if clean_req_student_id == DEMO_STUDENT_ID:
            student_id = DEMO_STUDENT_ID
        else:
            is_existing_student = False
            try:
                check_existing = await db_exec(
                    supabase.table("students")
                    .select("id")
                    .eq("id", clean_req_student_id)
                    .limit(1)
                )
                if check_existing.data and len(check_existing.data) > 0:
                    is_existing_student = True
            except Exception as e:
                print(f"[WARN] Student existence check fallback: {e}")

            if not is_existing_student:
                try:
                    sess_check = await db_exec(
                        supabase.table("sessions")
                        .select("id")
                        .eq("student_id", clean_req_student_id)
                        .limit(1)
                    )
                    if sess_check.data and len(sess_check.data) > 0:
                        is_existing_student = True
                except Exception:
                    pass

            if is_existing_student:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required: student profile already exists. Please supply a valid session or auth token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            student_id = clean_req_student_id
            try:
                upsert_payload = {"id": student_id, "name": req.student_name}
                if req.student_email:
                    upsert_payload["email"] = req.student_email.strip().lower()
                await db_exec(supabase.table("students").upsert(upsert_payload))
            except Exception:
                try:
                    await db_exec(supabase.table("students").upsert({"id": student_id, "name": req.student_name}))
                except Exception:
                    try:
                        unique_name = f"{req.student_name} #{student_id[:4]}"
                        await db_exec(supabase.table("students").insert({"id": student_id, "name": unique_name}))
                    except Exception as e:
                        print(f"[WARN] Student creation fallback: {e}")

    # Flow C: Anonymous/guest user
    if not student_id:
        student_id = str(uuid.uuid4())
        try:
            new_student = await db_exec(supabase.table("students").insert({"id": student_id, "name": req.student_name}))
            if new_student.data:
                student_id = new_student.data[0]["id"]
        except Exception:
            try:
                found = await db_exec(supabase.table("students").select("*").eq("name", req.student_name))
                if found.data:
                    student_id = found.data[0]["id"]
            except Exception as e:
                print(f"[WARN] Student lookup fallback: {e}")

    if not student_id:
        student_id = str(uuid.uuid4())

    mastery_rows = await db_exec(
        supabase.table("student_skill_mastery")
        .select("*")
        .eq("student_id", student_id)
    )
    mastery_state = initialize_mastery()
    for row in (mastery_rows.data or []):
        if row.get("skill_id") and row.get("mastery_prob") is not None:
            mastery_state[row["skill_id"]] = float(row["mastery_prob"])

    # Check recent active session to resume
    if req.student_id and student_id:
        try:
            recent_sess = await db_exec(
                supabase.table("sessions")
                .select("id, student_name")
                .eq("student_id", student_id)
                .order("started_at", desc=True)
                .limit(1)
            )
            if recent_sess.data and len(recent_sess.data) > 0:
                existing_session_id = recent_sess.data[0]["id"]
                existing_state = await asyncio.to_thread(get_session, existing_session_id)
                if existing_state and existing_state.get("current_problem"):
                    session_token = create_session_token(
                        student_id=student_id,
                        session_id=existing_session_id,
                        student_name=existing_state.get("student_name", req.student_name),
                    )
                    prob_title = existing_state["current_problem"].get("title", "your current problem")
                    active_misc = existing_state.get("active_misconceptions") or await asyncio.to_thread(get_student_misconceptions, student_id)
                    return {
                        "session_id": existing_session_id,
                        "student_id": student_id,
                        "student_name": existing_state.get("student_name", req.student_name),
                        "session_token": session_token,
                        "current_problem": _public_problem(existing_state["current_problem"]),
                        "mastery_state": existing_state.get("mastery_state", mastery_state),
                        "active_misconceptions": active_misc,
                        "welcome_message": f"Welcome back, {req.student_name}! Picking up right where we left off with **{prob_title}**. Let's keep solving!",
                        "resumed": True,
                    }
        except Exception as e:
            print(f"[WARN] Session resume lookup fallback: {e}")

    session_id = str(uuid.uuid4())
    try:
        await db_exec(supabase.table("sessions").insert({
            "id": session_id,
            "student_id": student_id,
            "student_name": req.student_name,
        }))
    except Exception as e:
        print(f"[WARN] Supabase session insert error: {e}")

    current_skill = get_next_skill(mastery_state)
    problem = await asyncio.to_thread(
        get_next_problem,
        skill_id=current_skill,
        mastery_prob=mastery_state.get(current_skill, 0.3),
        student_id=student_id,
    )

    if not problem:
        raise HTTPException(status_code=503, detail="No problems available. Please run seed script.")

    session_token = create_session_token(
        student_id=student_id,
        session_id=session_id,
        student_name=req.student_name,
    )

    active_misc = await asyncio.to_thread(get_student_misconceptions, student_id)
    state: TutorState = {
        "student_id": student_id,
        "student_name": req.student_name,
        "session_id": session_id,
        "conversation_history": [],
        "latest_input": "",
        "latest_image_bytes": None,
        "current_problem": _public_problem(problem),
        "current_problem_evaluation": problem,
        "current_problem_credited": False,
        "problems_attempted": [problem["id"]],
        "mastery_state": mastery_state,
        "current_skill_id": current_skill,
        "active_misconceptions": active_misc,
        "diagnosis": None,
        "agent_response": "",
        "thinking_steps": [],
        "next_action": None,
    }
    await asyncio.to_thread(save_session, session_id, state)

    return {
        "session_id": session_id,
        "student_id": student_id,
        "student_name": req.student_name,
        "session_token": session_token,
        "current_problem": _public_problem(problem),
        "mastery_state": mastery_state,
        "active_misconceptions": active_misc,
        "welcome_message": f"Hi {req.student_name}! I'm your math tutor. Let's start with this problem. Read it carefully, then tell me what you think the first step is!",
    }


@router.post("/reset")
async def reset_session_endpoint(
    req: ResetSessionRequest,
    auth: dict = Depends(verify_student_caller),
):
    """
    Reset student's practice session and skill mastery back to initial priors.
    Clears cached session state and Supabase student_skill_mastery, returning fresh problem #1.
    """
    try:
        uuid.UUID(req.student_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid student_id: Must be a valid UUID format.")

    supabase = get_supabase()
    caller_sub = auth.get("sub")
    clean_student_id = req.student_id.strip()
    if caller_sub != clean_student_id and auth.get("role") != "parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: caller {caller_sub} cannot reset progress for student {clean_student_id}",
        )

    if auth.get("role") == "parent" and caller_sub != clean_student_id:
        try:
            linked = await db_exec(
                supabase.table("children")
                .select("student_id")
                .eq("parent_id", caller_sub)
                .eq("student_id", clean_student_id)
                .limit(1)
            )
            if not linked.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: parent is not linked to this student",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: unable to verify parent-student relationship",
            )

    if req.session_id and auth.get("sid") and auth["sid"] != req.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session mismatch: token does not authorize this session reset",
        )

    if req.session_id:
        existing_sess = get_session(req.session_id)
        if existing_sess:
            sess_student = existing_sess.get("student_id")
            if sess_student and sess_student != clean_student_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: session {req.session_id} belongs to another student",
                )
        else:
            try:
                db_sess = await db_exec(
                    supabase.table("sessions")
                    .select("student_id")
                    .eq("id", req.session_id)
                    .limit(1)
                )
                if db_sess.data and db_sess.data[0].get("student_id") != clean_student_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied: session {req.session_id} belongs to another student",
                    )
            except HTTPException:
                raise
            except Exception as e:
                print(f"[WARN] Failed to verify session ownership in DB: {e}")

        evict_session(req.session_id)
    else:
        evict_student_sessions(clean_student_id)

    try:
        if req.session_id:
            await asyncio.to_thread(revoke_session_token, req.session_id)
            await db_exec(supabase.table("session_events").delete().eq("session_id", req.session_id))
            await db_exec(supabase.table("sessions").delete().eq("id", req.session_id))
        else:
            try:
                all_sess = await db_exec(
                    supabase.table("sessions").select("id").eq("student_id", clean_student_id)
                )
                for sr in (all_sess.data or []):
                    if sr.get("id"):
                        await asyncio.to_thread(revoke_session_token, sr["id"])
            except Exception as rev_e:
                logger.warning("Could not enumerate sessions for revocation during full reset: %s", rev_e)
            await db_exec(supabase.table("session_events").delete().eq("student_id", clean_student_id))
            await db_exec(supabase.table("sessions").delete().eq("student_id", clean_student_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to invalidate old sessions during reset: %s", e)
        raise HTTPException(status_code=503, detail="Could not safely invalidate the previous session.")

    try:
        await db_exec(
            supabase.table("student_skill_mastery")
            .delete()
            .eq("student_id", req.student_id)
        )
    except Exception as e:
        print(f"[WARN] Failed to delete student_skill_mastery on reset: {e}")

    await asyncio.to_thread(clear_student_misconceptions, clean_student_id)

    fresh_mastery = initialize_mastery()

    student_name = "Student"
    try:
        st_row = await db_exec(
            supabase.table("students")
            .select("name")
            .eq("id", req.student_id)
            .limit(1)
        )
        if st_row.data:
            student_name = st_row.data[0].get("name") or "Student"
    except Exception:
        pass

    new_session_id = str(uuid.uuid4())
    try:
        await db_exec(supabase.table("sessions").insert({
            "id": new_session_id,
            "student_id": req.student_id,
            "student_name": student_name,
        }))
    except Exception as e:
        print(f"[WARN] Error inserting new reset session: {e}")

    first_skill = get_next_skill(fresh_mastery)
    first_prob = await asyncio.to_thread(
        get_next_problem,
        skill_id=first_skill,
        mastery_prob=fresh_mastery.get(first_skill, 0.3),
        student_id=req.student_id,
        exclude_problem_ids=[],
    )
    if not first_prob:
        raise HTTPException(503, "No problems available in problem bank.")

    session_token = create_session_token(
        student_id=req.student_id,
        session_id=new_session_id,
        student_name=student_name,
    )

    fresh_state: TutorState = {
        "student_id": req.student_id,
        "student_name": student_name,
        "session_id": new_session_id,
        "conversation_history": [],
        "latest_input": "",
        "latest_image_bytes": None,
        "current_problem": _public_problem(first_prob),
        "current_problem_evaluation": first_prob,
        "current_problem_credited": False,
        "problems_attempted": [first_prob["id"]],
        "mastery_state": fresh_mastery,
        "current_skill_id": first_skill,
        "diagnosis": None,
        "agent_response": "",
        "thinking_steps": [],
        "next_action": None,
    }
    await asyncio.to_thread(save_session, new_session_id, fresh_state)

    return {
        "session_id": new_session_id,
        "student_id": req.student_id,
        "student_name": student_name,
        "session_token": session_token,
        "current_problem": _public_problem(first_prob),
        "mastery_state": fresh_mastery,
        "welcome_message": f"Welcome fresh, {student_name}! We've reset your practice session and mastery. Let's start from problem 1. Read it carefully and share your first thoughts!",
        "resumed": False,
    }


@router.post("/message")
async def send_message(
    req: MessageRequest,
    auth: dict = Depends(verify_session_access),
):
    """Send a student text message and get a streaming tutor response with safety guardrails."""
    if auth.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    if auth.get("sid") and auth["sid"] != req.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token issued for session {auth.get('sid')}, not {req.session_id}",
        )

    limiter.enforce_cooldown(
        key=f"msg_{req.session_id}",
        cooldown_seconds=1.5,
        action="message",
        max_per_minute=30,
    )

    state = await asyncio.to_thread(get_session, req.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    session_state: dict[str, Any] = state

    caller_sub = auth.get("sub")
    if caller_sub and caller_sub != session_state.get("student_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: caller does not own this tutoring session",
        )

    clean_message = sanitize_input(req.message)
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    is_injection, injection_reason = check_prompt_injection(clean_message)
    is_harmful, harm_category = check_harmful_content(clean_message)

    if is_injection:
        record_security_event("prompt_injection_blocked", {
            "session_id": req.session_id,
            "reason": injection_reason,
            "preview": clean_message[:80],
        })
        async def _injection_stream() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'response', 'content': SOCRATIC_BOUNDARY_RESPONSE, 'done': True})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'mastery_state': session_state.get('mastery_state', {}), 'problem_solved': False})}\n\n"
        return StreamingResponse(_injection_stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    if is_harmful:
        record_security_event("harmful_content_flagged", {
            "session_id": req.session_id,
            "category": harm_category,
        })

    session_state["latest_input"] = clean_message
    session_state["latest_image_bytes"] = None

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async with get_session_lock(req.session_id):
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Analyzing response...'})}\n\n"

                thinking_step_initial = "Reading your thought..."
                yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_step_initial})}\n\n"
                await asyncio.sleep(0.1)

                latest_state = await asyncio.to_thread(get_session, req.session_id)
                current_state = latest_state or session_state
                current_prob = current_state.get("current_problem") or {}

                safety_flag = "harmful" if is_harmful else ("injection" if is_injection else None)
                graph_input: TutorState = {
                    "student_id": current_state.get("student_id", ""),
                    "student_name": current_state.get("student_name", ""),
                    "session_id": req.session_id,
                    "conversation_history": list(current_state.get("conversation_history") or []),
                    "latest_input": clean_message,
                    "latest_image_bytes": None,
                    "current_problem": current_prob,
                    "current_problem_evaluation": current_state.get("current_problem_evaluation") or current_prob,
                    "current_problem_credited": current_state.get("current_problem_credited", False),
                    "problems_attempted": list(current_state.get("problems_attempted") or []),
                    "mastery_state": dict(current_state.get("mastery_state") or {}),
                    "current_skill_id": current_prob.get("skill_id") or current_state.get("current_skill_id", ""),
                    "active_misconceptions": dict(current_state.get("active_misconceptions") or {}),
                    "diagnosis": current_state.get("diagnosis"),
                    "agent_response": "",
                    "thinking_steps": [thinking_step_initial],
                    "safety_flag": safety_flag,
                    "next_action": None,
                }

                try:
                    graph = get_orchestrator_graph()
                except Exception as g_err:
                    print(f"[ERROR] On-demand LangGraph compilation failed: {g_err}")
                    yield f"data: {json.dumps({'type': 'response', 'content': 'The AI reasoning engine is currently warming up. Please send your message again in a moment!', 'done': True})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'mastery_state': current_state.get('mastery_state', {}), 'problem_solved': False})}\n\n"
                    return

                graph_output = await graph.ainvoke(graph_input)

                response = graph_output.get("agent_response", "")
                problem_solved = bool(graph_output.get("problem_solved", False))
                steps = graph_output.get("thinking_steps") or []
                for step_content in steps:
                    if step_content != thinking_step_initial:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': step_content})}\n\n"

                current_state["latest_input"] = clean_message
                current_state["latest_image_bytes"] = None
                current_state["conversation_history"] = graph_output.get("conversation_history", current_state.get("conversation_history", []))
                current_state["thinking_steps"] = steps
                current_state["mastery_state"] = graph_output.get("mastery_state", current_state.get("mastery_state", {}))
                current_state["active_misconceptions"] = graph_output.get("active_misconceptions", current_state.get("active_misconceptions", {}))
                current_state["current_problem_credited"] = graph_output.get("current_problem_credited", current_state.get("current_problem_credited", False))

                is_final_attempt = graph_output.get("is_final_attempt")
                turn_correctness: bool | None = True if problem_solved else (False if is_final_attempt else None)

                await asyncio.to_thread(save_session, req.session_id, current_state)
                await asyncio.to_thread(
                    record_session_event,
                    session_id=req.session_id,
                    student_id=current_state["student_id"],
                    problem_id=current_prob.get("id"),
                    attempt_text=clean_message,
                    is_correct=turn_correctness,
                    agent_response=response,
                )
                final_mastery = current_state.get("mastery_state", {})

            words = response.split(" ")
            accumulated = ""
            for i, word in enumerate(words):
                accumulated += word + (" " if i < len(words) - 1 else "")
                if i % 3 == 0 or i == len(words) - 1:
                    yield f"data: {json.dumps({'type': 'response', 'content': accumulated, 'done': i == len(words) - 1})}\n\n"
                    await asyncio.sleep(0.04)

            yield f"data: {json.dumps({'type': 'done', 'mastery_state': final_mastery, 'problem_solved': problem_solved})}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[ERROR] Chat stream exception: {e}")
            fallback_msg = "I had a quick pause! Could you repeat that thought?"
            yield f"data: {json.dumps({'type': 'response', 'content': fallback_msg, 'done': True})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'mastery_state': session_state.get('mastery_state', {}), 'problem_solved': False})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/next-problem")
async def next_problem_endpoint(
    req: NextProblemRequest,
    auth: dict = Depends(verify_session_access),
):
    """Explicitly advance to the next tailored practice problem with BKT mastery progression."""
    if auth.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    if auth.get("sid") and auth["sid"] != req.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token issued for session {auth.get('sid')}, not {req.session_id}",
        )

    async with get_session_lock(req.session_id):
        state = await asyncio.to_thread(get_session, req.session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        session_state: dict[str, Any] = state

        caller_sub = auth.get("sub")
        if caller_sub and caller_sub != session_state.get("student_id"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: caller does not own this tutoring session",
            )
        current_prob = session_state.get("current_problem") or {}
        curr_skill = current_prob.get("skill_id") or session_state.get("current_skill_id")

        if req.mark_previous_correct and curr_skill and curr_skill in session_state.get("mastery_state", {}):
            if not session_state.get("current_problem_credited", False):
                await _update_mastery_for_skill(session_state, curr_skill)

        next_skill = get_next_skill(session_state.get("mastery_state", {}))
        attempted = list(session_state.get("problems_attempted", []))
        if current_prob.get("id") and current_prob["id"] not in attempted:
            attempted.append(current_prob["id"])

        next_prob = await asyncio.to_thread(
            get_next_problem,
            skill_id=next_skill,
            mastery_prob=session_state.get("mastery_state", {}).get(next_skill, 0.3),
            student_id=session_state["student_id"],
            exclude_problem_ids=attempted,
        )
        if not next_prob:
            next_prob = await asyncio.to_thread(
                get_next_problem,
                skill_id=next_skill,
                mastery_prob=session_state.get("mastery_state", {}).get(next_skill, 0.3),
                student_id=session_state["student_id"],
                exclude_problem_ids=[],
            )

        if not next_prob:
            raise HTTPException(status_code=503, detail="No further practice problems found in problem bank.")

        session_state["current_problem"] = next_prob
        session_state["current_problem_evaluation"] = next_prob
        session_state["current_problem_credited"] = False
        session_state["current_skill_id"] = next_skill
        if next_prob.get("id") and next_prob["id"] not in attempted:
            attempted.append(next_prob["id"])
        session_state["problems_attempted"] = attempted

        problem_title = next_prob.get("title", "Next Problem")
        if req.mark_previous_correct:
            tutor_intro = (
                f"Awesome work! Here is your next problem: **{problem_title}**. "
                f"Read it carefully and let me know what you think the first step is!"
            )
        else:
            tutor_intro = (
                f"Here is your next practice problem: **{problem_title}**. "
                f"Take a moment to read it and share what you think we should do first!"
            )
        session_state["conversation_history"].append({
            "role": "tutor",
            "content": tutor_intro,
            "problem_id": next_prob.get("id"),
        })

        await asyncio.to_thread(save_session, req.session_id, session_state)
        await asyncio.to_thread(
            record_session_event,
            session_id=req.session_id,
            student_id=session_state["student_id"],
            problem_id=next_prob.get("id"),
            attempt_text="Advanced to next problem",
            is_correct=None,
            agent_response=tutor_intro,
        )

        return {
            "status": "ok",
            "current_problem": _public_problem(next_prob),
            "mastery_state": session_state["mastery_state"],
            "tutor_message": tutor_intro,
        }


@router.post("/upload-work")
async def upload_work(
    session_id: str,
    file: UploadFile = File(...),
    auth: dict = Depends(verify_session_access),
):
    """Upload a photo of student handwritten work for OCR + diagnosis with strict upload validation."""
    if auth.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student session authentication required",
        )
    if auth.get("sid") and auth["sid"] != session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session mismatch: token issued for session {auth.get('sid')}, not {session_id}",
        )

    limiter.enforce_cooldown(
        key=f"upload_{session_id}",
        cooldown_seconds=3.0,
        action="work upload",
        max_per_minute=10,
    )

    state = await asyncio.to_thread(get_session, session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    caller_sub = auth.get("sub")
    if caller_sub and caller_sub != state.get("student_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: caller does not own this tutoring session",
        )

    content_length = file.headers.get("content-length") if file.headers else None
    if content_length:
        try:
            if int(content_length) > 10 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Uploaded image is too large. Maximum allowed is 10MB.")
        except ValueError:
            pass

    image_bytes = await file.read(10 * 1024 * 1024 + 1)

    validate_image_upload(
        file_bytes=image_bytes,
        content_type=file.content_type,
        filename=file.filename,
    )

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async with get_session_lock(session_id):
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Reading your handwritten work...'})}\n\n"
                await asyncio.sleep(0.1)

                fresh_state = await asyncio.to_thread(get_session, session_id)
                current_state = fresh_state or state
                current_problem = current_state.get("current_problem") or {}
                evaluation_problem = current_state.get("current_problem_evaluation") or current_problem
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Checking your steps...'})}\n\n"

                diagnosis = await asyncio.to_thread(
                    run_diagnostic_agent,
                    image_bytes=image_bytes,
                    expected_steps=evaluation_problem.get("expected_steps", []),
                    problem_text=current_problem.get("text", ""),
                    skill_id=current_state.get("current_skill_id", ""),
                )

                try:
                    await asyncio.to_thread(
                        cloudinary_service.upload_student_work,
                        image_bytes,
                        session_id,
                        current_state.get("student_id"),
                    )
                except Exception as c_err:
                    print(f"[WARN] Cloudinary student work upload skipped/failed: {c_err}")

                misconception = diagnosis.get('misconception_type', 'unknown')
                friendly_misc = misconception.replace('_', ' ')
                yield f"data: {json.dumps({'type': 'thinking', 'content': 'Checking step: ' + friendly_misc})}\n\n"

                curr_skill = current_problem.get("skill_id") or current_state.get("current_skill_id")
                is_correct = diagnosis.get("is_correct", False)

                if not is_correct and curr_skill:
                    raw_curr = current_state["mastery_state"].get(curr_skill)
                    cur_val = float(raw_curr) if raw_curr is not None else 0.3
                    new_mastery = update_mastery(
                        current_mastery=cur_val,
                        is_correct=False,
                        skill_id=curr_skill,
                    )
                    current_state["mastery_state"][curr_skill] = round(new_mastery, 4)
                    mastery_pct = f"{new_mastery*100:.0f}%"
                    yield f"data: {json.dumps({'type': 'thinking', 'content': 'Updating skill progress: ' + mastery_pct})}\n\n"
                    try:
                        supabase = get_supabase()
                        await db_exec(supabase.table("student_skill_mastery").upsert({
                            "student_id": current_state["student_id"],
                            "skill_id": curr_skill,
                            "mastery_prob": new_mastery,
                        }, on_conflict="student_id,skill_id"))
                    except Exception as e:
                        print(f"[WARN] Supabase write failed: {e}")

                    if misconception and misconception not in ("unknown", "temporary_system_pause"):
                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        active_map = current_state.setdefault("active_misconceptions", {})
                        entry = active_map.get(misconception, {
                            "count": 0,
                            "last_seen": now_iso,
                            "resolved": False,
                            "skill_id": curr_skill or "",
                        })
                        entry["count"] = entry.get("count", 0) + 1
                        entry["last_seen"] = now_iso
                        entry["resolved"] = False
                        if curr_skill:
                            entry["skill_id"] = curr_skill
                        active_map[misconception] = entry
                        await asyncio.to_thread(
                            save_student_misconception,
                            current_state["student_id"],
                            misconception,
                            curr_skill or "",
                            False,
                        )

                try:
                    await asyncio.to_thread(
                        record_session_event,
                        session_id=current_state["session_id"],
                        student_id=current_state["student_id"],
                        problem_id=current_problem.get("id"),
                        attempt_text=diagnosis.get("ocr_text", ""),
                        is_correct=is_correct,
                        agent_response=diagnosis.get("corrective_question", ""),
                    )
                except Exception as e:
                    print(f"[WARN] Supabase write failed: {e}")

                current_state["diagnosis"] = diagnosis
                await asyncio.to_thread(save_session, session_id, current_state)

                if is_correct:
                    if curr_skill:
                        await _update_mastery_for_skill(current_state, curr_skill)
                        active_map = current_state.setdefault("active_misconceptions", {})
                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        for m_type, m_info in active_map.items():
                            if m_info.get("skill_id") == curr_skill and not m_info.get("resolved"):
                                m_info["resolved"] = True
                                m_info["resolved_at"] = now_iso
                        await asyncio.to_thread(resolve_student_misconceptions_for_skill, current_state["student_id"], curr_skill)

                    raw_cur_m = current_state["mastery_state"].get(curr_skill)
                    cur_m = float(raw_cur_m) if raw_cur_m is not None else 0.3
                    mastery_pct = f"{cur_m*100:.0f}%"
                    yield f"data: {json.dumps({'type': 'thinking', 'content': 'Updating skill progress: ' + mastery_pct})}\n\n"

                    yield f"data: {json.dumps({'type': 'thinking', 'content': 'Picking your next practice problem...'})}\n\n"
                    next_skill = get_next_skill(current_state["mastery_state"])
                    misconception_desc = diagnosis.get("description") or diagnosis.get("misconception_type")
                    raw_next_m = current_state["mastery_state"].get(next_skill)
                    next_m_val = float(raw_next_m) if raw_next_m is not None else 0.3
                    next_problem = await asyncio.to_thread(
                        get_next_problem,
                        skill_id=next_skill,
                        mastery_prob=next_m_val,
                        student_id=current_state["student_id"],
                        exclude_problem_ids=current_state.get("problems_attempted", []),
                        misconception_text=misconception_desc,
                    )
                    if next_problem:
                        current_state["current_problem"] = next_problem
                        current_state["current_problem_evaluation"] = next_problem
                        current_state["current_problem_credited"] = False
                        current_state["current_skill_id"] = next_skill
                        current_state["problems_attempted"] = current_state.get("problems_attempted", []) + [next_problem["id"]]
                        await asyncio.to_thread(save_session, session_id, current_state)

                yield f"data: {json.dumps({'type': 'diagnosis', 'diagnosis': diagnosis, 'mastery_state': current_state['mastery_state'], 'active_misconceptions': current_state.get('active_misconceptions', {}), 'next_problem': _public_problem(current_state.get('current_problem'))})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[ERROR] upload_work stream failed: {e}")
            yield f"data: {json.dumps({'type': 'thinking', 'content': 'Recovering from analysis hiccup...'})}\n\n"
            fallback_diag = {
                "ocr_text": "Could not complete analysis",
                "is_correct": False,
                "step_number": 1,
                "misconception_type": "temporary_system_pause",
                "description": "The system encountered a brief delay processing this request.",
                "skill_gap": state.get("current_skill_id", ""),
                "skill_gap_name": "",
                "corrective_question": "I had a momentary glitch reading your work. Can you describe what step you took, or try uploading once more?",
                "bounding_hint": {"x": 10.0, "y": 20.0, "width": 80.0, "height": 22.0},
                "bounding_box": {"x": 10.0, "y": 20.0, "width": 80.0, "height": 22.0},
            }
            yield f"data: {json.dumps({'type': 'diagnosis', 'diagnosis': fallback_diag, 'mastery_state': state['mastery_state'], 'next_problem': state.get('current_problem')})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
