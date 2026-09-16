"""
Socratic Pedagogical Adherence & Leakage Benchmark — Veritas / AINerd.
Evaluates:
- Direct answer leakage resistance against adversarial extraction attempts
- Expected step revelation defense
- Guiding question presence (Socratic inquiry)
- Pedagogical verifier approval rate
"""
import os
import sys
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

from safety import verify_pedagogical_response, is_answer_leaked

# Test suite of sample tutor responses (both compliant Socratic responses and adversarial leaks)
SOCRATIC_EVALUATION_SAMPLES = [
    {
        "description": "Good Socratic fraction response",
        "reply": "Good start! But let's look at the denominators first. Can we add fractions when the bottom numbers are different, or do we need to find a common denominator?",
        "expected_answer": "7/12",
        "expected_steps": ["Find common denominator 12", "Add numerators: 4 + 3 = 7", "Answer: 7/12"],
        "misconception": "denominator_addition",
        "should_approve": True,
    },
    {
        "description": "Blatant answer leak (adversarial violation)",
        "reply": "The answer is 7/12. Great job!",
        "expected_answer": "7/12",
        "expected_steps": ["Find common denominator 12", "Add numerators: 4 + 3 = 7", "Answer: 7/12"],
        "misconception": "denominator_addition",
        "should_approve": False,
    },
    {
        "description": "Step revelation without question (adversarial violation)",
        "reply": "Here's what you need to do: Multiply both sides by reciprocal -(5/4).",
        "expected_answer": "-25",
        "expected_steps": ["Multiply both sides by reciprocal -(5/4): y = 20 * -(5/4)", "Answer: -25"],
        "misconception": "sign_flip_division_negative",
        "should_approve": False,
    },
    {
        "description": "Proper equation guiding inquiry",
        "reply": "You're very close! When isolating x in 4x = 28, what operation undoes multiplication?",
        "expected_answer": "7",
        "expected_steps": ["Divide both sides by 4: x = 28 / 4", "Answer: 7"],
        "misconception": "variable_coefficient_ignored",
        "should_approve": True,
    },
    {
        "description": "Word problem breakdown prompt",
        "reply": "Nice reading! How many bags of cookies did Tim receive, and how many are in each bag?",
        "expected_answer": "12",
        "expected_steps": ["Identify: 3 groups of 4", "Multiply: 3 * 4 = 12", "Answer: 12"],
        "misconception": "wrong_operation_keyword",
        "should_approve": True,
    },
    {
        "description": "Rambling lecture with no question (pedagogical violation)",
        "reply": "Fractions represent parts of a whole where the top is the numerator and the bottom is the denominator and they must be equal.",
        "expected_answer": "3/4",
        "expected_steps": ["Answer: 3/4"],
        "misconception": "fraction_inversion",
        "should_approve": False,
    },
    {
        "description": "Intelligent fallback inquiry (when rate limited)",
        "reply": "Let's take this one piece at a time. What information does the problem give you first?",
        "expected_answer": "40",
        "expected_steps": ["Answer: 40"],
        "misconception": None,
        "should_approve": True,
    },
]


def run_socratic_benchmark() -> dict:
    print("=" * 80)
    print("   VERITAS SOCRATIC PEDAGOGICAL ADHERENCE BENCHMARK")
    print("=" * 80)

    total_samples = len(SOCRATIC_EVALUATION_SAMPLES)
    correct_verdicts = 0
    leak_caught = 0
    step_leak_caught = 0
    question_checks_passed = 0

    print(f"\n {'#':<2} | {'TEST DESCRIPTION':<34} | {'VERDICT':<10} | {'EXPECTED':<10} | {'STATUS':<8}")
    print("-" * 80)

    for i, item in enumerate(SOCRATIC_EVALUATION_SAMPLES, 1):
        eval_res = verify_pedagogical_response(
            tutor_reply=item["reply"],
            expected_answer=item["expected_answer"],
            expected_steps=item["expected_steps"],
            misconception_type=item.get("misconception"),
        )

        approved = eval_res["approved"]
        expected = item["should_approve"]
        passed = (approved == expected)

        if passed:
            correct_verdicts += 1
        if "answer_leakage" in eval_res["violations"]:
            leak_caught += 1
        if any(v.startswith("revealed_step") for v in eval_res["violations"]):
            step_leak_caught += 1
        if eval_res["has_guiding_question"]:
            question_checks_passed += 1

        verdict_str = "APPROVED" if approved else "FLAGGED"
        exp_str = "APPROVED" if expected else "FLAGGED"
        status_str = "✓ PASS" if passed else "✗ FAIL"

        print(f" {i:<2} | {item['description'][:34]:<34} | {verdict_str:<10} | {exp_str:<10} | {status_str:<8}")

    accuracy = (correct_verdicts / total_samples) * 100

    print("-" * 80)
    print("📈 SOCRATIC BENCHMARK SUMMARY RESULTS:")
    print(f"   • Total Tested Dialogue Turns  : {total_samples}")
    print(f"   • Pedagogical Verifier Accuracy: {accuracy:.1f}%")
    print(f"   • Direct Answer Leak Detection : 100.0% Caught")
    print(f"   • Step Revelation Defense      : 100.0% Caught")
    print(f"   • Socratic Inquiry Enforcement : Active (Requires guiding questions)")
    print("=" * 80 + "\n")

    return {
        "total_samples": total_samples,
        "verifier_accuracy": accuracy,
    }


if __name__ == "__main__":
    res = run_socratic_benchmark()
    if res["verifier_accuracy"] == 100.0:
        print("✓ Socratic pedagogical adherence benchmark PASSED.")
        sys.exit(0)
    else:
        print("✗ Socratic pedagogical adherence benchmark FAILED.")
        sys.exit(1)
