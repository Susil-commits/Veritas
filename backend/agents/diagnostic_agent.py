"""
Diagnostic Agent — OCR + misconception detection using Gemini Vision.
Identifies SPECIFIC errors in student handwritten work, not generic "wrong answer."
"""
# pyright: reportMissingImports=false, reportMissingModuleSource=false
import os
import base64
import json
import re
import hashlib
from typing import Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from config import VISION_MODEL, VISION_MODEL_CASCADE, extract_clean_text

# Real misconception examples from Eedi/NeurIPS 2020 education research
# These few-shot examples teach the model to name SPECIFIC misconceptions
EEDI_FEW_SHOT_MISCONCEPTIONS = """
MISCONCEPTION LIBRARY (use these categories when diagnosing):

1. "sign_flip_division_negative" — Student flips the inequality/sign when dividing by a positive (should only flip for negative)
   Example: 2x < 8 → student writes x > 4 instead of x < 4

2. "fraction_inversion" — Student inverts numerator and denominator when they shouldn't
   Example: 3/4 + 1/4 → student computes 4/3 + 4/1

3. "wrong_operation_keyword" — Student uses wrong operation despite correct keywords (e.g., "total" → multiplication instead of addition)
   Example: "3 bags of 4 apples" → student adds 3+4=7 instead of 3×4=12

4. "denominator_addition" — Student adds denominators when adding fractions (most common fraction error)
   Example: 1/3 + 1/4 = 2/7 instead of 7/12

5. "place_value_confusion" — Student misreads place values in multi-digit operations
   Example: 34 × 5 → student treats 3 as ones, computes 4×5 + 3 = 23

6. "order_of_operations_skip" — Student ignores PEMDAS/BODMAS (e.g., adds before multiplying)
   Example: 2 + 3 × 4 → student computes 5 × 4 = 20 instead of 2 + 12 = 14

7. "carry_error" — Student forgets to carry in multi-digit addition/multiplication
   Example: 47 + 38 → gets 75 instead of 85

8. "negative_number_confusion" — Student treats negative numbers as positive in operations
   Example: -3 + (-4) → student computes 3 + 4 = 7

9. "variable_coefficient_ignored" — Student ignores the coefficient when solving equations
   Example: 3x = 12 → student writes x = 12 instead of x = 4

10. "step_skipped_correctly" — No error found; student's logic is sound
"""

DIAGNOSTIC_SYSTEM_PROMPT = f"""You are an expert math education diagnostician.
Your job is to analyze a student's handwritten work and identify the SPECIFIC misconception that caused an error.

{EEDI_FEW_SHOT_MISCONCEPTIONS}

You will receive:
1. An image of the student's handwritten work (if provided)
2. The expected solution steps for the problem

Your task:
1. First, READ the student's handwritten work carefully (OCR it mentally)
2. Compare it step-by-step against the expected solution
3. Identify exactly WHERE the reasoning broke and WHAT misconception caused it
4. Return ONLY a JSON object (no markdown, no explanation outside the JSON)

Output format:
{{
  "ocr_text": "exact text you read from the handwriting",
  "is_correct": false,
  "step_number": 2,
  "misconception_type": "denominator_addition",
  "description": "Student added the denominators (1/3 + 1/4 = 2/7) instead of finding a common denominator. This is the most common fraction addition error.",
  "skill_gap": "4.NF.B.3",
  "skill_gap_name": "Adding and subtracting fractions",
  "corrective_question": "When we add fractions, can we add the bottom numbers? What do we need to make the denominators the same first?",
  "bounding_hint": {{
    "x": 12.0,
    "y": 38.0,
    "width": 76.0,
    "height": 22.0
  }}
}}

For bounding_hint:
- If is_correct is false, return an object specifying the percentage coordinates (0 to 100) highlighting the student's erroneous step on the image:
  - x: percentage from left edge (0 to 100)
  - y: percentage from top edge (0 to 100)
  - width: percentage width of error area (0 to 100)
  - height: percentage height of error area (0 to 100)
- If is_correct is true, return null for bounding_hint.

If the work is correct, set is_correct=true, misconception_type="step_skipped_correctly", and bounding_hint=null.
Be specific and educational — a teacher should be able to show this diagnosis to a student."""


def build_vision_llm(model_name: str | None = None) -> ChatGoogleGenerativeAI:
    selected = model_name or os.environ.get("GEMINI_VISION_MODEL") or VISION_MODEL
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return ChatGoogleGenerativeAI(
        model=selected,
        google_api_key=api_key,
        max_output_tokens=2048,
        max_retries=0,
        timeout=15,
    )


def normalize_bounding_box(data: dict) -> tuple[dict | None, str, float]:
    """
    Ensure coordinates {x, y, width, height} are valid percentages (0-100).
    Returns (bounding_box_or_none, localization_source, localization_confidence).
    Distinguishes genuine 'model' localization from 'fallback' (null).
    """
    if data.get("is_correct"):
        return None, "model", 1.0
    raw = data.get("bounding_hint") or data.get("bounding_box")
    if isinstance(raw, dict):
        try:
            x = float(raw.get("x", raw.get("left", 10.0)))
            y = float(raw.get("y", raw.get("top", 35.0)))
            width = float(raw.get("width", 80.0))
            height = float(raw.get("height", 22.0))
            if 0 <= x <= 95 and 0 <= y <= 95 and width > 5 and height > 5:
                return {
                    "x": round(min(max(x, 5.0), 85.0), 1),
                    "y": round(min(max(y, 5.0), 85.0), 1),
                    "width": round(min(max(width, 10.0), 90.0), 1),
                    "height": round(min(max(height, 8.0), 40.0), 1),
                }, "model", 1.0
        except (ValueError, TypeError):
            pass

    # When model does not provide valid coordinates, do NOT generate a fake box!
    return None, "fallback", 0.0


# Bounded in-memory diagnosis cache to avoid re-invoking Vision LLM on duplicate uploads
_DIAGNOSTIC_CACHE: dict[str, dict] = {}


def run_diagnostic_agent(
    image_bytes: bytes | None,
    expected_steps: list[str],
    problem_text: str,
    skill_id: str,
) -> dict:
    """
    Run the diagnostic agent on a student's handwritten work.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG) of handwritten work. None for text-only.
        expected_steps: List of correct solution steps (for comparison).
        problem_text: The problem the student is solving.
        skill_id: The target skill.

    Returns:
        dict with ocr_text, is_correct, misconception_type, description, skill_gap, corrective_question, bounding_hint
    """
    # Fast-path: Never invoke Vision LLM when no image is provided
    if not image_bytes:
        res = {
            "ocr_text": "",
            "is_correct": False,
            "step_number": 1,
            "misconception_type": "no_image_provided",
            "description": "No handwritten work image was attached.",
            "skill_gap": skill_id,
            "skill_gap_name": "",
            "corrective_question": "Please take a photo of your handwritten math work and upload it.",
            "bounding_box": None,
            "bounding_hint": None,
            "localization_source": "fallback",
            "localization_confidence": 0.0,
        }
        return res

    # Check cache for duplicate upload within session
    cache_key = hashlib.sha256(image_bytes + problem_text.encode("utf-8", errors="ignore")).hexdigest()
    if cache_key in _DIAGNOSTIC_CACHE:
        return _DIAGNOSTIC_CACHE[cache_key]

    context = f"""Problem: {problem_text}
Expected Steps:
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(expected_steps))}
Target Skill: {skill_id}"""

    try:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        print(f"[ERROR] Failed to base64-encode image bytes: {e}")
        fallback_err: dict[str, Any] = {
            "ocr_text": "Failed to decode image",
            "is_correct": False,
            "step_number": 1,
            "misconception_type": "image_decode_failure",
            "description": "The image data was corrupted or in an unsupported format.",
            "skill_gap": skill_id,
            "skill_gap_name": "",
            "corrective_question": "There was an issue processing that photo file. Could you try uploading as a standard JPEG or PNG?",
        }
        box, source, conf = normalize_bounding_box(fallback_err)
        fallback_err["bounding_hint"] = box
        fallback_err["bounding_box"] = box
        fallback_err["localization_source"] = source
        fallback_err["localization_confidence"] = conf
        return fallback_err

    # Detect image format from header magic bytes
    mime_type = "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        mime_type = "image/webp"

    messages = [
        SystemMessage(content=DIAGNOSTIC_SYSTEM_PROMPT),
        HumanMessage(
            content=[
                {"type": "text", "text": context},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                },
            ]
        ),
    ]

    # Zero-credit test mode bypass (used by automated test suites to consume 0 Gemini API credits)
    is_mocked = hasattr(build_vision_llm, "mock_calls") or hasattr(build_vision_llm, "assert_called")
    if not is_mocked and (os.environ.get("VERITAS_TEST_MODE") == "true" or os.environ.get("VERITAS_MOCK_LLM") == "true"):
        mock_data: dict[str, Any] = {
            "ocr_text": "3/4 + 1/4 = 4/4 = 1",
            "is_correct": True,
            "step_number": 1,
            "misconception_type": "none",
            "description": "Student correctly solved problem step-by-step.",
            "skill_gap": skill_id,
            "skill_gap_name": "Core Math Concept",
            "corrective_question": "Can you explain how you verified your final answer?",
            "bounding_box": {"x": 10.0, "y": 20.0, "width": 80.0, "height": 30.0},
            "bounding_hint": {"x": 10.0, "y": 20.0, "width": 80.0, "height": 30.0},
            "localization_source": "mock_test",
            "localization_confidence": 1.0,
        }
        return mock_data

    raw = ""
    last_err: Exception | None = None
    seen = set()
    models_to_try = [m for m in VISION_MODEL_CASCADE if m and not (m in seen or seen.add(m))]

    for m_name in models_to_try:
        try:
            llm = build_vision_llm(m_name)
            response = llm.invoke(messages)  # type: ignore[arg-type]
            raw = extract_clean_text(response.content)
            if raw:
                break
        except Exception as e:
            last_err = e
            print(f"[WARN] Diagnostic agent vision call on '{m_name}' failed: {e}")

    if not raw and last_err is not None:
        e = last_err
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str or "rate" in err_str:
            res: dict[str, Any] = {
                "ocr_text": "[Rate Limit Encountered]",
                "is_correct": False,
                "step_number": 1,
                "misconception_type": "rate_limit_pause",
                "description": "The Vision AI service reached its temporary per-minute rate limit.",
                "skill_gap": skill_id,
                "skill_gap_name": "",
                "corrective_question": "Our AI vision tutor is catching its breath! Please try submitting again in about 10 seconds, or type out what you wrote.",
            }
            box, source, conf = normalize_bounding_box(res)
            res["bounding_hint"] = box
            res["bounding_box"] = box
            res["localization_source"] = source
            res["localization_confidence"] = conf
            return res
        elif "image" in err_str or "decode" in err_str or "format" in err_str:
            res = {
                "ocr_text": "[Image format unreadable]",
                "is_correct": False,
                "step_number": 1,
                "misconception_type": "unreadable_image",
                "description": "The uploaded photo could not be parsed as a readable image.",
                "skill_gap": skill_id,
                "skill_gap_name": "",
                "corrective_question": "That photo seems a bit blurry or dark. Could you take another picture with more light, or type your next step?",
            }
            box, source, conf = normalize_bounding_box(res)
            res["bounding_hint"] = box
            res["bounding_box"] = box
            res["localization_source"] = source
            res["localization_confidence"] = conf
            return res
        else:
            res = {
                "ocr_text": "[Analysis temporarily unavailable]",
                "is_correct": False,
                "step_number": 1,
                "misconception_type": "service_interruption",
                "description": "Temporary service disruption during image analysis.",
                "skill_gap": skill_id,
                "skill_gap_name": "",
                "corrective_question": "I had a momentary glitch reading your paper. Can you try uploading once more or type your answer?",
            }
            box, source, conf = normalize_bounding_box(res)
            res["bounding_hint"] = box
            res["bounding_box"] = box
            res["localization_source"] = source
            res["localization_confidence"] = conf
            return res

    # Extract JSON object using regex to handle potential conversational wrappers
    clean_text = raw.strip()
    clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r"\s*```$", "", clean_text).strip()

    json_match = re.search(r"\{[\s\S]*\}", clean_text)
    clean_json = json_match.group(0) if json_match else clean_text

    try:
        parsed_data = json.loads(clean_json)
        # Ensure critical keys are present
        if not isinstance(parsed_data, dict):
            raise ValueError("Parsed JSON is not a dictionary")

        data: dict[str, Any] = dict(parsed_data)
        if not data.get("ocr_text"):
            data["ocr_text"] = "Handwriting analyzed"
        if not data.get("corrective_question"):
            data["corrective_question"] = "Can you walk me through your steps out loud?"

        box, source, conf = normalize_bounding_box(data)
        data["bounding_hint"] = box
        data["bounding_box"] = box
        data["localization_source"] = source
        data["localization_confidence"] = conf
        if len(_DIAGNOSTIC_CACHE) > 50:
            _DIAGNOSTIC_CACHE.pop(next(iter(_DIAGNOSTIC_CACHE)))
        _DIAGNOSTIC_CACHE[cache_key] = data
        return data
    except Exception as parse_err:
        print(f"[WARN] Failed to parse diagnostic JSON: {parse_err}. Raw text: {raw[:150]}")
        # Pedagogical fallback for unreadable or badly formatted response
        fallback: dict[str, Any] = {
            "ocr_text": "Handwriting was difficult to read",
            "is_correct": False,
            "step_number": 1,
            "misconception_type": "blurry_or_unclear_photo",
            "description": "The handwriting in this photo was too blurry or faint to parse with confidence.",
            "skill_gap": skill_id,
            "skill_gap_name": "",
            "corrective_question": "I couldn't quite make out all your pencil marks in that photo! Could you try taking a clearer photo in good lighting, or tell me what step you wrote down?",
        }
        box, source, conf = normalize_bounding_box(fallback)
        fallback["bounding_hint"] = box
        fallback["bounding_box"] = box
        fallback["localization_source"] = source
        fallback["localization_confidence"] = conf
        return fallback
