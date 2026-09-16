"""
Tutor Agent — Socratic dialogue, never gives the answer.
Uses Google Gemini via centralized config.
"""
# pyright: reportMissingImports=false, reportMissingModuleSource=false
import os
import json
import re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from config import CHAT_MODEL, CHAT_MODEL_CASCADE


def _parse_tutor_response(raw: str, fallback_text: str) -> dict:
    """Parse the tutor LLM's JSON response. Falls back to old keyword-matching if parsing fails."""
    clean_text = raw.strip()
    clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r"\s*```$", "", clean_text).strip()

    json_match = re.search(r"\{[\s\S]*\}", clean_text)
    clean_json = json_match.group(0) if json_match else clean_text

    try:
        data = json.loads(clean_json)
        if not isinstance(data, dict) or not data.get("reply"):
            raise ValueError("Missing reply field")
        extracted_ans = data.get("extracted_student_answer")
        return {
            "reply": str(data["reply"]).strip(),
            "problem_solved": bool(data.get("problem_solved", False)),
            "is_final_attempt": bool(data["is_final_attempt"]) if "is_final_attempt" in data and data["is_final_attempt"] is not None else None,
            "extracted_student_answer": str(extracted_ans).strip() if extracted_ans else None,
            "student_reasoning": str(data.get("student_reasoning", "")).strip() or None,
        }
    except Exception as parse_err:
        print(f"[WARN] Failed to parse tutor JSON: {parse_err}. Raw text: {raw[:150]}")
        # Fallback: use the raw text as the reply, and fall back to the old
        # keyword heuristic so a parsing failure never breaks the "solved" signal entirely.
        congrats_signals = [
            "spot on", "correct!", "that's right", "thats right", "great job", "you got it",
            "wonderful work", "excellent", "nailed it", "well done", "perfect!", "exactly right",
            "you solved it", "you arrived at the correct"
        ]
        resp_lower = fallback_text.lower()
        return {
            "reply": fallback_text,
            "problem_solved": any(s in resp_lower for s in congrats_signals),
            "is_final_attempt": None,
            "extracted_student_answer": None,
            "student_reasoning": None,
        }


SOCRATIC_SYSTEM_PROMPT = """You are an expert math tutor using the Socratic method.

CRITICAL RULE: You MUST NEVER directly give the student the answer or the next step.
Instead, ask ONE guiding question at a time that helps them discover the answer themselves.

Your approach:
1. Acknowledge what they got right first (positive reinforcement)
2. If they're stuck, ask a simpler question that points toward the key insight
3. If they made an error, ask them to re-examine a specific part: "Let's look at step 2 again — what operation did you perform there?"
4. Use real-world analogies when helpful (e.g., fractions → pizza slices)
5. Keep responses SHORT — 1-3 sentences max, then a guiding question
6. Match energy to the student's age/level (be warm, encouraging, not condescending)

Misconception patterns to watch for:
- "Flipped operation" → Ask: "You multiplied here — what operation is the problem asking for?"
- "Sign error" → Ask: "What happens to the inequality sign when we divide by a negative number?"
- "Fraction numerator/denominator confusion" → Ask: "Which part of a fraction tells us how many pieces we have?"
- "Place value error" → Ask: "What does the digit in the tens place represent?"

Current problem context will be provided in the conversation.
Remember: Guide, don't tell. Questions, not answers.

RESPONSE FORMAT: Respond with ONLY a JSON object, no other text, in this exact shape:
{
  "reply": "<your Socratic response to the student, 1-3 sentences plus a guiding question>",
  "extracted_student_answer": "<string of student's proposed answer if any, or null if discussing steps/asking questions>",
  "student_reasoning": "<brief 1-sentence description of student's reasoning/strategy>",
  "problem_solved": <true if the student's final answer to THIS problem is now fully correct and complete, false otherwise — false if they only made partial progress, a good step, or a correct intermediate calculation that isn't the final answer>,
  "is_final_attempt": <true if the student explicitly asserted or proposed a final answer to the problem, false if they are asking a question, discussing intermediate steps, or stuck>
}
Only set problem_solved to true when the student has reached the actual final answer to the problem, not for encouraging partial progress."""

# Few-shot examples based on GSM8K style
FEW_SHOT_EXAMPLES = [
    {
        "student": "I got 15. I added 7 and 8.",
        "tutor": "Good start! You identified the two numbers correctly. But let's re-read the problem — is it asking us to combine those amounts, or find the difference? What word in the problem gives you a clue?"
    },
    {
        "student": "I don't know what to do.",
        "tutor": "That's okay — let's break it down together. What information does the problem give us? Can you tell me just the numbers you see?"
    },
    {
        "student": "Is the answer 3/8?",
        "tutor": "Interesting! Walk me through how you got that. What did you do with the two fractions first?"
    }
]


MODEL_CASCADE = CHAT_MODEL_CASCADE


def build_tutor_llm(model_name: str) -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=0.7,
        max_output_tokens=1000,
        max_retries=0,
        timeout=10,
    )


def _intelligent_socratic_fallback(
    student_message: str,
    current_problem: dict | None = None,
) -> str:
    """Provide pedagogical Socratic guidance even when external LLM APIs are momentarily rate-limited."""
    clean = student_message.strip().lower()
    
    # Check for common stuck cues
    if any(w in clean for w in ["stuck", "don't know", "dont know", "hint", "help", "what next", "lost"]):
        return (
            "Let's take this one piece at a time. "
            "What information does the problem give you first?"
        )

    # Check if student gave a number / answer
    has_digit = any(c.isdigit() for c in clean)
    if has_digit:
        return (
            "Nice effort putting a calculation forward! Walk me through your thinking: "
            "which numbers did you use and what operation did you perform?"
        )

    if current_problem:
        title = current_problem.get("title", "this problem")
        return (
            f"You're on the right track exploring {title}! "
            f"What math operation do you think we need to use here — addition, subtraction, multiplication, or division?"
        )

    return "Good thought! Can you explain why you chose that approach, or what step comes next?"


def run_tutor_agent(
    student_message: str,
    conversation_history: list[dict],
    current_problem: dict | None = None,
) -> dict:
    """
    Given a student message and conversation history, return a Socratic guiding response.
    conversation_history: list of {"role": "student"|"tutor", "content": str}
    """
    # Build system message with current problem context
    system_content = SOCRATIC_SYSTEM_PROMPT
    if current_problem:
        system_content += f"""

CURRENT PROBLEM:
Title: {current_problem.get('title', '')}
Problem: {current_problem.get('text', '')}
Skill: {current_problem.get('skill_name', '')}
Difficulty: {current_problem.get('difficulty', 1)}/5

Expected solution steps (for your reference only — do NOT reveal these):
{chr(10).join(f"Step {i+1}: {s}" for i, s in enumerate(current_problem.get('expected_steps', [])))}
"""

    messages: list[BaseMessage] = [SystemMessage(content=system_content)]

    # Add few-shot examples
    for ex in FEW_SHOT_EXAMPLES:
        messages.append(HumanMessage(content=ex["student"]))
        messages.append(AIMessage(content=ex["tutor"]))

    # Add conversation history
    for turn in conversation_history[-10:]:  # last 10 turns max
        if turn["role"] == "student":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))

    # Add current student message
    messages.append(HumanMessage(content=student_message))

    # Try model cascade to handle individual model quota/deprecations seamlessly
    last_err = None
    # Deduplicate cascade preserving order
    seen = set()
    models_to_try = [m for m in MODEL_CASCADE if m and not (m in seen or seen.add(m))]

    for model_name in models_to_try:
        try:
            llm = build_tutor_llm(model_name)
            response = llm.invoke(messages)
            text = str(response.content).strip()
            if text:
                return _parse_tutor_response(text, text)
        except Exception as e:
            last_err = e
            print(f"[WARN] Tutor agent invoke failed on model '{model_name}': {e}")
            continue

    print(f"[WARN] All models in cascade failed ({last_err}), using intelligent Socratic fallback.")
    fallback_text = _intelligent_socratic_fallback(student_message, current_problem)
    return {"reply": fallback_text, "problem_solved": False, "is_final_attempt": None}
