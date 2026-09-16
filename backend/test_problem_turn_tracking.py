"""
Test Problem Turn Tracking and Attempt-Type Classification across Problem Transitions.
Verifies that student turns on Problem 1 do not cause attempts on Problem 2 to be
erroneously classified as 'corrected_after_feedback'.
"""
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph.orchestrator import tutor_node, TutorState


def run_async(coro):
    return asyncio.run(coro)


def test_problem_turn_tracking_isolation():
    print("\n[TEST] Verifying problem turn tracking across problem transitions...")

    prob_1 = {
        "id": "prob_arith_01",
        "title": "Problem 1",
        "skill_id": "4.OA.A.1",
        "expected_steps": ["Answer: 10"],
    }
    prob_2 = {
        "id": "prob_frac_02",
        "title": "Problem 2",
        "skill_id": "4.NF.A.1",
        "expected_steps": ["Answer: 1/2"],
    }

    # Turn 1 on Problem 1 (Incorrect first attempt)
    state_turn1: TutorState = {
        "student_id": "student_test_123",
        "current_problem": prob_1,
        "conversation_history": [],
        "latest_input": "I think the answer is 7",
        "thinking_steps": [],
        "current_problem_credited": False,
        "mastery_state": {"4.OA.A.1": 0.3},
    }

    with patch("graph.orchestrator.run_tutor_agent") as mock_tutor:
        mock_tutor.return_value = {
            "reply": "Not quite 7. What if you check your addition again?",
            "problem_solved": False,
            "is_final_attempt": False,
            "extracted_student_answer": "7",
        }
        res1 = run_async(tutor_node(state_turn1))

    assert res1["problem_solved"] is False
    assert len(res1["conversation_history"]) == 2
    assert res1["conversation_history"][0]["problem_id"] == "prob_arith_01"
    assert res1["conversation_history"][1]["problem_id"] == "prob_arith_01"

    # Turn 2 on Problem 1 (Corrected second attempt)
    state_turn2: TutorState = {
        "student_id": "student_test_123",
        "current_problem": prob_1,
        "conversation_history": res1["conversation_history"],
        "latest_input": "Oh, 10!",
        "thinking_steps": [],
        "current_problem_credited": False,
        "mastery_state": res1["mastery_state"],
    }

    with patch("graph.orchestrator.run_tutor_agent") as mock_tutor:
        mock_tutor.return_value = {
            "reply": "Great job, 10 is correct!",
            "problem_solved": True,
            "is_final_attempt": True,
            "extracted_student_answer": "10",
        }
        res2 = run_async(tutor_node(state_turn2))

    assert res2["problem_solved"] is True
    # Verify mastery was updated with corrected_after_feedback
    m_after_p1 = res2["mastery_state"]["4.OA.A.1"]
    print(f"   Problem 1 solved after feedback. Mastery: {m_after_p1:.4f}")

    # Now transition to Problem 2:
    # Append tutor intro for problem 2
    history_with_p2 = list(res2["conversation_history"]) + [
        {"role": "tutor", "content": "Welcome to Problem 2!", "problem_id": "prob_frac_02"}
    ]

    # Turn 1 on Problem 2: Student gives correct answer on their FIRST attempt on Problem 2
    state_p2_turn1: TutorState = {
        "student_id": "student_test_123",
        "current_problem": prob_2,
        "conversation_history": history_with_p2,
        "latest_input": "1/2",
        "thinking_steps": [],
        "current_problem_credited": False,
        "mastery_state": {"4.OA.A.1": m_after_p1, "4.NF.A.1": 0.3},
    }

    with patch("graph.orchestrator.run_tutor_agent") as mock_tutor, \
         patch("graph.orchestrator.update_mastery") as mock_bkt:
        mock_tutor.return_value = {
            "reply": "Excellent! 1/2 is correct.",
            "problem_solved": True,
            "is_final_attempt": True,
            "extracted_student_answer": "1/2",
        }
        mock_bkt.return_value = 0.6857

        res_p2 = run_async(tutor_node(state_p2_turn1))

        # Check the attempt_type passed to update_mastery!
        mock_bkt.assert_called_once()
        _, kwargs = mock_bkt.call_args
        called_attempt_type = kwargs.get("attempt_type")
        assert called_attempt_type == "independent_attempt", (
            f"Expected 'independent_attempt' for first attempt on Problem 2, but got '{called_attempt_type}'! "
            f"Turns from Problem 1 must not leak into Problem 2 attempt classification."
        )

    print(f"   [OK] First attempt on Problem 2 correctly classified as: '{called_attempt_type}'")
    print("   [OK] Problem turn tracking successfully isolated across problem transitions!")


if __name__ == "__main__":
    test_problem_turn_tracking_isolation()
    print("\n=== PROBLEM TURN TRACKING TESTS PASSED! ===")
