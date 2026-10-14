"""
LangGraph Orchestrator — State machine orchestrating Safety Boundary & Socratic Tutor agents.
Routes between: Safety Shield (harmful/injection boundary) and Socratic Tutor.
"""
# pyright: reportMissingImports=false, reportMissingModuleSource=false
import asyncio
import datetime
import warnings
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
from typing import TypedDict, Literal, Any
from langgraph.graph import StateGraph, END, START

from agents.tutor_agent import run_tutor_agent
from agents.diagnostic_agent import run_diagnostic_agent
from agents.content_agent import get_next_problem
from bkt.tracker import update_mastery, get_next_skill
from db.supabase_client import get_supabase
from evaluators.math_evaluator import evaluate_student_solution, extract_expected_answer
from session_manager import resolve_student_misconceptions_for_skill, save_student_misconception
from safety import (
    SOCRATIC_BOUNDARY_RESPONSE,
    SAFE_SUPPORT_RESPONSE,
    is_answer_leaked,
)


# ── State Schema ────────────────────────────────────────────────────────────

class TutorState(TypedDict, total=False):
    # Session metadata
    student_id: str
    student_name: str
    session_id: str

    # Conversation
    conversation_history: list[dict]     # [{"role": "student"|"tutor", "content": str}]
    latest_input: str                    # latest student text message
    latest_image_bytes: bytes | None     # latest uploaded photo
    image_present: bool                  # convenience flag for visual scratchpad routing

    # Current problem
    current_problem: dict | None
    current_problem_evaluation: dict | None  # full private problem (expected_steps, answer, solution) for evaluation
    current_problem_credited: bool       # True once problem solved and mastery credited
    problems_attempted: list[str]        # problem IDs seen this session

    # Next problem (selected by content agent)
    next_problem: dict | None

    # Mastery
    mastery_state: dict[str, float]      # {skill_id: probability}
    current_skill_id: str

    # Misconceptions (longitudinal learner model beside BKT)
    active_misconceptions: dict[str, dict]  # {misconception_type: {"count": int, "last_seen": str, "resolved": bool, "skill_id": str}}

    # Diagnosis result (set by diagnostic agent after photo upload)
    diagnosis: dict | None

    # Agent output
    agent_response: str
    thinking_steps: list[str]           # streamed to UI for transparency
    problem_solved: bool
    is_final_attempt: bool | None

    # Routing & Safety
    safety_flag: Literal["harmful", "injection"] | None
    next_action: Literal["safety", "tutor", "diagnostic", "content", "end"] | None


# ── Node Functions ───────────────────────────────────────────────────────────

async def safety_node(state: TutorState) -> dict:
    """Safety boundary agent — intercepts harmful or jailbreak prompts with pedagogical redirection."""
    flag = state.get("safety_flag")
    if flag == "harmful":
        response = SAFE_SUPPORT_RESPONSE
    else:
        response = SOCRATIC_BOUNDARY_RESPONSE

    steps = list(state.get("thinking_steps") or [])
    steps.append("Safety shield: intercepted prompt and applied pedagogical boundary")

    curr_prob = state.get("current_problem") or {}
    curr_prob_id = curr_prob.get("id")

    history = list(state.get("conversation_history") or [])
    if state.get("latest_input"):
        student_msg = {"role": "student", "content": state.get("latest_input", "")}
        if curr_prob_id:
            student_msg["problem_id"] = curr_prob_id
        history.append(student_msg)
    tutor_msg = {"role": "tutor", "content": response}
    if curr_prob_id:
        tutor_msg["problem_id"] = curr_prob_id
    history.append(tutor_msg)

    return {
        "agent_response": response,
        "conversation_history": history,
        "thinking_steps": steps,
        "problem_solved": False,
        "is_final_attempt": False,
        "next_action": None,
    }


async def diagnostic_node(state: TutorState) -> dict:
    """
    Diagnostic Vision agent — runs OCR + misconception detection using Gemini Vision on uploaded work.
    Extracts step breakdowns, localized error coordinates, and tags pedagogical misconceptions.
    Feeds downstream into tutor_node for Socratic guidance.
    """
    steps = list(state.get("thinking_steps") or [])
    steps.append("Diagnostic Vision agent: analyzing handwritten math scratchpad...")

    image_bytes = state.get("latest_image_bytes")
    current_prob = state.get("current_problem_evaluation") or state.get("current_problem") or {}
    expected_steps = current_prob.get("expected_steps") or []
    problem_text = str(current_prob.get("text") or current_prob.get("title") or "")
    skill_id = str(current_prob.get("skill_id") or state.get("current_skill_id") or "")

    diagnosis = await asyncio.to_thread(
        run_diagnostic_agent,
        image_bytes=image_bytes,
        expected_steps=expected_steps,
        problem_text=problem_text,
        skill_id=skill_id,
    )

    is_correct = bool(diagnosis.get("is_correct", False))
    misc_type = str(diagnosis.get("misconception_type", "unknown"))
    steps.append(f"Diagnostic Vision agent: diagnosis complete (is_correct={is_correct}, misconception={misc_type})")

    mastery_state = dict(state.get("mastery_state") or {})
    active_misc = dict(state.get("active_misconceptions") or {})
    student_id = state.get("student_id")
    credited = state.get("current_problem_credited", False)

    if not is_correct and skill_id:
        raw_curr = mastery_state.get(skill_id)
        cur_val = float(raw_curr) if raw_curr is not None else 0.3
        new_mastery = update_mastery(
            current_mastery=cur_val,
            is_correct=False,
            skill_id=skill_id,
        )
        mastery_state[skill_id] = round(new_mastery, 4)
        if student_id:
            await asyncio.to_thread(_save_mastery, student_id, skill_id, new_mastery)

        if misc_type and misc_type not in ("unknown", "temporary_system_pause", "none", "step_skipped_correctly"):
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = active_misc.get(misc_type, {
                "count": 0,
                "last_seen": now_str,
                "resolved": False,
                "skill_id": skill_id,
            })
            entry["count"] = entry.get("count", 0) + 1
            entry["last_seen"] = now_str
            entry["resolved"] = False
            entry["skill_id"] = skill_id
            active_misc[misc_type] = entry
            if student_id:
                await asyncio.to_thread(
                    save_student_misconception,
                    student_id,
                    misc_type,
                    skill_id,
                    False,
                )
    elif is_correct and skill_id:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for m_info in active_misc.values():
            if isinstance(m_info, dict) and m_info.get("skill_id") == skill_id and not m_info.get("resolved"):
                m_info["resolved"] = True
                m_info["resolved_at"] = now_str
        if student_id:
            await asyncio.to_thread(resolve_student_misconceptions_for_skill, student_id, skill_id)

        if not credited:
            raw_curr = mastery_state.get(skill_id)
            cur_val = float(raw_curr) if raw_curr is not None else 0.3
            new_m = update_mastery(
                current_mastery=cur_val,
                is_correct=True,
                skill_id=skill_id,
                attempt_type="independent_attempt",
            )
            mastery_state[skill_id] = round(new_m, 4)
            if student_id:
                await asyncio.to_thread(_save_mastery, student_id, skill_id, new_m)
            credited = True

    return {
        "diagnosis": diagnosis,
        "problem_solved": is_correct,
        "is_final_attempt": True,
        "thinking_steps": steps,
        "mastery_state": mastery_state,
        "active_misconceptions": active_misc,
        "current_problem_credited": credited,
    }


async def tutor_node(state: TutorState) -> dict:
    """
    Socratic tutor — responds to student text messages using Socratic inquiry.
    When preceded by diagnostic_node, the diagnosis feeds directly into the tutor's prompt.
    """
    steps = list(state.get("thinking_steps") or [])
    steps.append("Tutor agent: formulating Socratic response...")

    latest_input = state.get("latest_input", "")
    conversation_history = list(state.get("conversation_history") or [])
    current_prob = state.get("current_problem_evaluation") or state.get("current_problem") or {}
    active_misc = dict(state.get("active_misconceptions") or {})
    diagnosis = state.get("diagnosis")
    prev_solved = state.get("problem_solved", False)

    # Diagnosis feeds tutor prompt
    tutor_result = await asyncio.to_thread(
        run_tutor_agent,
        student_message=latest_input,
        conversation_history=conversation_history,
        current_problem=current_prob,
        active_misconceptions=active_misc,
        diagnosis=diagnosis,
    )

    if prev_solved and diagnosis and diagnosis.get("is_correct"):
        response = (
            "Spot on! Your handwritten work is completely correct step-by-step. "
            "Fantastic job working through this problem! Click 'Next Challenge' when you're ready."
        )
        problem_solved = True
        is_final_attempt = True
        extracted_answer = None
    elif isinstance(tutor_result, dict):
        response = tutor_result.get("reply", "")
        problem_solved = bool(tutor_result.get("problem_solved", False))
        is_final_attempt = tutor_result.get("is_final_attempt")
        extracted_answer = tutor_result.get("extracted_student_answer")
    else:
        response = str(tutor_result)
        problem_solved = False
        is_final_attempt = None
        extracted_answer = None

    # Deterministic Objective Math Validator: Verify student candidate mathematically
    if latest_input and current_prob and not diagnosis:
        eval_input = extracted_answer or latest_input
        math_eval = evaluate_student_solution(eval_input, current_prob)
        if not math_eval.get("objective_solved") and extracted_answer:
            raw_eval = evaluate_student_solution(latest_input, current_prob)
            if raw_eval.get("objective_solved"):
                math_eval = raw_eval

        if math_eval.get("eval_type") != "none":
            if math_eval.get("objective_solved"):
                problem_solved = True
                is_final_attempt = True
                steps.append(f"Math Validator: {math_eval.get('match_reason')}")
            elif math_eval.get("is_explicit_attempt") and not math_eval.get("objective_solved"):
                if problem_solved:
                    print(f"[INFO] Overriding LLM problem_solved to False via objective validator: {math_eval.get('match_reason')}")
                problem_solved = False
                is_final_attempt = True

    # Secondary safety check: Prevent accidental final answer disclosure during guidance
    canonical_ans, _ = extract_expected_answer(current_prob) if current_prob else (None, "none")
    prob_ans = current_prob.get("answer") or canonical_ans or ""
    if not problem_solved and prob_ans and is_answer_leaked(response, str(prob_ans)):
        response = (
            "That's a great direction! Let's pause right before the final calculation: "
            "what math property explains why this step works?"
        )
        problem_solved = False

    curr_prob_id = current_prob.get("id")

    # Update conversation history with problem_id tagging
    history = list(conversation_history)
    effective_student_text = latest_input
    if not effective_student_text and diagnosis:
        ocr_snippet = diagnosis.get("ocr_text", "").strip()
        effective_student_text = f"[Uploaded scratchpad: {ocr_snippet}]" if ocr_snippet else "[Uploaded handwritten work photo]"

    if effective_student_text:
        new_student_turn = {"role": "student", "content": effective_student_text}
        if curr_prob_id:
            new_student_turn["problem_id"] = curr_prob_id
        history.append(new_student_turn)

    new_tutor_turn = {"role": "tutor", "content": response}
    if curr_prob_id:
        new_tutor_turn["problem_id"] = curr_prob_id
    history.append(new_tutor_turn)

    steps.append("Problem solved! Ready for next challenge." if problem_solved else "Thinking of a guiding question...")

    # Determine attempt_type
    if curr_prob_id and any("problem_id" in m for m in conversation_history):
        student_turns_on_prob = [
            m for m in conversation_history
            if m.get("role") == "student" and m.get("problem_id") == curr_prob_id
        ]
    else:
        student_turns_on_prob = [
            m for m in conversation_history
            if m.get("role") == "student"
        ]
    is_hint_requested = any("hint" in str(m.get("content", "")).lower() for m in student_turns_on_prob) or ("hint" in latest_input.lower())
    if is_hint_requested:
        attempt_type = "hinted_attempt"
    elif len(student_turns_on_prob) > 0:
        attempt_type = "corrected_after_feedback"
    else:
        attempt_type = "independent_attempt"

    # Credit mastery if newly solved via text
    mastery_state = dict(state.get("mastery_state") or {})
    curr_skill = current_prob.get("skill_id") or state.get("current_skill_id")
    credited = state.get("current_problem_credited", False)
    if problem_solved and curr_skill:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for m_type, m_info in active_misc.items():
            if m_info.get("skill_id") == curr_skill and not m_info.get("resolved"):
                m_info["resolved"] = True
                m_info["resolved_at"] = now_iso
        student_id = state.get("student_id")
        if student_id:
            await asyncio.to_thread(resolve_student_misconceptions_for_skill, student_id, curr_skill)

        if not credited:
            raw_curr = mastery_state.get(curr_skill)
            cur_val = float(raw_curr) if raw_curr is not None else 0.3
            new_m = update_mastery(
                current_mastery=cur_val,
                is_correct=True,
                skill_id=curr_skill,
                attempt_type=attempt_type,
            )
            mastery_state[curr_skill] = round(new_m, 4)
            if student_id:
                await asyncio.to_thread(_save_mastery, student_id, curr_skill, new_m)
            credited = True

    return {
        "agent_response": response,
        "conversation_history": history,
        "thinking_steps": steps,
        "problem_solved": problem_solved,
        "is_final_attempt": is_final_attempt,
        "mastery_state": mastery_state,
        "active_misconceptions": active_misc,
        "current_problem_credited": credited,
        "next_action": None,
    }


async def content_node(state: TutorState) -> dict:
    """
    Adaptive Content agent — selects next ZPD-targeted problem using pgvector RAG + BKT mastery.
    Invoked when problem_solved is True or when explicitly transitioning to the next problem.
    """
    steps = list(state.get("thinking_steps") or [])
    steps.append("Adaptive Content agent: selecting next ZPD-targeted challenge...")

    mastery_state = dict(state.get("mastery_state") or {})
    next_skill = get_next_skill(mastery_state)
    raw_next_m = mastery_state.get(next_skill)
    mastery_prob = float(raw_next_m) if raw_next_m is not None else 0.3
    student_id = str(state.get("student_id") or "default")

    attempted = list(state.get("problems_attempted") or [])
    curr_prob = state.get("current_problem") or {}
    if curr_prob.get("id") and curr_prob["id"] not in attempted:
        attempted.append(curr_prob["id"])

    diagnosis = state.get("diagnosis") or {}
    misc_type = diagnosis.get("misconception_type")
    misc_text = f"{misc_type}: {diagnosis.get('description', '')}" if misc_type and misc_type not in ("none", "unknown", "step_skipped_correctly") else None

    next_prob = await asyncio.to_thread(
        get_next_problem,
        skill_id=next_skill,
        mastery_prob=mastery_prob,
        student_id=student_id,
        exclude_problem_ids=attempted,
        misconception_text=misc_text,
    )
    if not next_prob:
        next_prob = await asyncio.to_thread(
            get_next_problem,
            skill_id=next_skill,
            mastery_prob=mastery_prob,
            student_id=student_id,
            exclude_problem_ids=[],
            misconception_text=misc_text,
        )

    if next_prob and next_prob.get("id") and next_prob["id"] not in attempted:
        attempted.append(next_prob["id"])

    prob_title = next_prob.get("title", "Next Challenge") if next_prob else "Practice Problem"
    steps.append(f"Adaptive Content agent: matched '{prob_title}' for skill standard {next_skill}")

    return {
        "next_problem": next_prob,
        "problems_attempted": attempted,
        "thinking_steps": steps,
        "current_skill_id": next_skill,
    }


# ── Routing ─────────────────────────────────────────────────────────────────

def entry_router(state: TutorState) -> str:
    """
    Route from START:
    - If safety flag present -> safety
    - If student uploaded image -> diagnostic
    - If explicit content transition -> content
    - Otherwise -> tutor
    """
    if state.get("safety_flag") in ("harmful", "injection"):
        return "safety"
    if state.get("latest_image_bytes") is not None or state.get("image_present"):
        return "diagnostic"
    if state.get("next_action") == "content":
        return "content"
    return "tutor"


def tutor_router(state: TutorState) -> str:
    """Route from tutor: transition to content agent only when problem_solved is True; otherwise END."""
    if state.get("problem_solved"):
        return "content"
    return END


# ── Graph Assembly ───────────────────────────────────────────────────────────

def build_graph() -> Any:
    """
    Compile complete 4-agent Veritas LangGraph State Machine:
    1. safety_node: Safety Boundary Agent
    2. diagnostic_node: Diagnostic Vision Agent
    3. tutor_node: Socratic Tutor Agent
    4. content_node: Adaptive Content Agent
    """
    builder = StateGraph(TutorState)

    builder.add_node("safety", safety_node)
    builder.add_node("diagnostic", diagnostic_node)
    builder.add_node("tutor", tutor_node)
    builder.add_node("content", content_node)

    # Safety: always ends with redirection returned to client
    builder.add_edge("safety", END)

    # Diagnostic: feeds directly into tutor's Socratic dialogue
    builder.add_edge("diagnostic", "tutor")

    # Tutor: conditional edge -> content if problem_solved else END
    builder.add_conditional_edges("tutor", tutor_router, {
        "content": "content",
        END: END,
    })

    # Content: always ends (provides next problem)
    builder.add_edge("content", END)

    # Entry point conditional routing
    builder.add_conditional_edges(START, entry_router, {
        "safety": "safety",
        "diagnostic": "diagnostic",
        "tutor": "tutor",
        "content": "content",
    })

    return builder.compile()


# ── Supabase Helpers ─────────────────────────────────────────────────────────

def _save_mastery(student_id: str, skill_id: str, mastery_prob: float):
    try:
        supabase = get_supabase()
        supabase.table("student_skill_mastery").upsert({
            "student_id": student_id,
            "skill_id": skill_id,
            "mastery_prob": mastery_prob,
        }, on_conflict="student_id,skill_id").execute()
    except Exception as e:
        print(f"[WARN] Failed to save mastery: {e}")


