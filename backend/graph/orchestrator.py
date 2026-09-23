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
from bkt.tracker import update_mastery
from db.supabase_client import get_supabase
from evaluators.math_evaluator import evaluate_student_solution
from session_manager import resolve_student_misconceptions_for_skill
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

    # Current problem
    current_problem: dict | None
    current_problem_evaluation: dict | None  # full private problem (expected_steps, answer, solution) for evaluation
    current_problem_credited: bool       # True once problem solved and mastery credited
    problems_attempted: list[str]        # problem IDs seen this session

    # Mastery
    mastery_state: dict[str, float]      # {skill_id: probability}
    current_skill_id: str

    # Misconceptions (longitudinal learner model beside BKT)
    active_misconceptions: dict[str, dict]  # {misconception_type: {"count": int, "last_seen": str, "resolved": bool, "skill_id": str}}

    # Diagnosis result (set after photo upload)
    diagnosis: dict | None

    # Agent output
    agent_response: str
    thinking_steps: list[str]           # streamed to UI for transparency
    problem_solved: bool
    is_final_attempt: bool | None

    # Routing & Safety
    safety_flag: Literal["harmful", "injection"] | None
    next_action: Literal["safety", "tutor", "end"] | None


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


async def tutor_node(state: TutorState) -> dict:
    """Socratic tutor — responds to student text messages using Socratic inquiry."""
    steps = list(state.get("thinking_steps") or [])
    steps.append("Tutor agent: formulating Socratic response...")

    latest_input = state.get("latest_input", "")
    conversation_history = list(state.get("conversation_history") or [])
    current_prob = state.get("current_problem_evaluation") or state.get("current_problem") or {}

    active_misc = dict(state.get("active_misconceptions") or {})

    tutor_result = await asyncio.to_thread(
        run_tutor_agent,
        student_message=latest_input,
        conversation_history=conversation_history,
        current_problem=current_prob,
        active_misconceptions=active_misc,
    )
    if isinstance(tutor_result, dict):
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
    # Conceptual path: Student answer -> LLM extracts answer/reasoning -> deterministic math evaluator -> correct/incorrect -> BKT
    if latest_input and current_prob:
        # Check extracted answer first, with fallback to full input
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
                # Student submitted an explicit incorrect answer — override any premature LLM "solved" claim
                if problem_solved:
                    print(f"[INFO] Overriding LLM problem_solved to False via objective validator: {math_eval.get('match_reason')}")
                problem_solved = False
                is_final_attempt = True

    # Secondary safety check: Prevent accidental final answer disclosure
    prob_ans = current_prob.get("answer") or ""
    if prob_ans and is_answer_leaked(response, str(prob_ans)):
        response = (
            "That's a great direction! Let's pause right before the final calculation: "
            "what math property explains why this step works?"
        )
        problem_solved = False

    curr_prob_id = current_prob.get("id")

    # Update conversation history with problem_id tagging
    new_student_turn = {"role": "student", "content": latest_input}
    new_tutor_turn = {"role": "tutor", "content": response}
    if curr_prob_id:
        new_student_turn["problem_id"] = curr_prob_id
        new_tutor_turn["problem_id"] = curr_prob_id

    history = conversation_history + [new_student_turn, new_tutor_turn]

    steps.append("Problem solved! Ready for next challenge." if problem_solved else "Thinking of a guiding question...")

    # Determine attempt_type:
    # - "corrected_after_feedback": if previous student turns exist on this problem
    # - "hinted_attempt": if student message requested a hint
    # - "independent_attempt": first attempt unassisted
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

    # If problem solved, credit mastery with pedagogical attempt-type weighting
    # and mark active misconceptions for this skill as resolved
    mastery_state = dict(state.get("mastery_state") or {})
    curr_skill = current_prob.get("skill_id") or state.get("current_skill_id")
    credited = state.get("current_problem_credited", False)
    if problem_solved and curr_skill:
        # Resolve active misconceptions for current skill
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for m_type, m_info in active_misc.items():
            if m_info.get("skill_id") == curr_skill and not m_info.get("resolved"):
                m_info["resolved"] = True
                m_info["resolved_at"] = now_iso
        student_id = state.get("student_id")
        if student_id:
            await asyncio.to_thread(resolve_student_misconceptions_for_skill, student_id, curr_skill)

        if not credited:
            new_m = update_mastery(
                current_mastery=mastery_state.get(curr_skill, 0.3),
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


# ── Routing ─────────────────────────────────────────────────────────────────

def entry_router(state: TutorState) -> str:
    """Route from START based on safety signals or text message."""
    if state.get("safety_flag") in ("harmful", "injection"):
        return "safety"
    return "tutor"


# ── Graph Assembly ───────────────────────────────────────────────────────────

def build_graph() -> Any:
    builder = StateGraph(TutorState)

    builder.add_node("safety", safety_node)
    builder.add_node("tutor", tutor_node)

    # Safety: always ends (redirection returned to frontend)
    builder.add_edge("safety", END)

    # Tutor: always ends (response returned to frontend)
    builder.add_edge("tutor", END)

    # Entry point: dynamic routing based on safety signals or message
    builder.add_conditional_edges(START, entry_router, {
        "safety": "safety",
        "tutor": "tutor",
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

