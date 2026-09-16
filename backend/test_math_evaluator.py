"""
Unit tests for Deterministic Objective Math Evaluator.
Verifies arithmetic, fractions, equations, expressions, and incorrect answer rejection.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluators.math_evaluator import evaluate_student_solution, verify_math_equivalence


def test_arithmetic_evaluation():
    print("\n[TEST 1] Testing Arithmetic & Integer Word Problem Evaluation...")
    prob = {
        "title": "Sticker Packs",
        "expected_steps": [
            "Calculate: 5 * 8 = 40",
            "Answer: Jake has 40 stickers",
        ]
    }

    # Correct integer assertions
    res1 = evaluate_student_solution("I got 40", prob)
    assert res1["objective_solved"] is True, f"Failed on 'I got 40': {res1}"

    res2 = evaluate_student_solution("The answer is 40 stickers!", prob)
    assert res2["objective_solved"] is True, f"Failed on '40 stickers': {res2}"

    res3 = evaluate_student_solution("40.0", prob)
    assert res3["objective_solved"] is True, f"Failed on '40.0': {res3}"

    # Incorrect integer assertions
    wrong_res = evaluate_student_solution("I think the answer is 20", prob)
    assert wrong_res["objective_solved"] is False, "Incorrect answer must not be marked solved"
    assert wrong_res["is_explicit_attempt"] is True
    assert wrong_res["student_answer_extracted"] == "20"
    print("   [OK] Integer arithmetic verified (40 recognized, 20 rejected).")


def test_fraction_and_decimal_equivalence():
    print("\n[TEST 2] Testing Fraction & Decimal Mathematical Equivalence...")
    prob = {
        "title": "Fraction Shading",
        "expected_steps": ["Answer: 3/4"],
    }

    # Equivalent fractions
    assert evaluate_student_solution("is it 3/4?", prob)["objective_solved"] is True
    assert evaluate_student_solution("The simplified fraction is 6/8", prob)["objective_solved"] is True
    assert evaluate_student_solution("Decimal form is 0.75", prob)["objective_solved"] is True

    # Non-equivalent fraction
    wrong_frac = evaluate_student_solution("5/8", prob)
    assert wrong_frac["objective_solved"] is False
    print("   [OK] Fraction equivalence verified (3/4 == 6/8 == 0.75; 5/8 rejected).")


def test_mixed_fractions():
    print("\n[TEST 3] Testing Mixed Fraction Evaluation...")
    prob = {
        "title": "Running Distance",
        "expected_steps": ["Answer: Ana ran 1 1/2 miles"],
    }

    assert evaluate_student_solution("1 1/2", prob)["objective_solved"] is True
    assert evaluate_student_solution("3/2", prob)["objective_solved"] is True
    assert evaluate_student_solution("1.5", prob)["objective_solved"] is True
    assert evaluate_student_solution("2 1/2", prob)["objective_solved"] is False
    print("   [OK] Mixed fractions verified (1 1/2 == 3/2 == 1.5; 2 1/2 rejected).")


def test_algebraic_equations():
    print("\n[TEST 4] Testing Algebraic Equations & Expression Evaluation...")
    prob_eq = {
        "title": "Solve for x",
        "expected_steps": ["Answer: x = 5"],
    }

    assert evaluate_student_solution("x = 5", prob_eq)["objective_solved"] is True
    assert evaluate_student_solution("5", prob_eq)["objective_solved"] is True
    assert evaluate_student_solution("x = 6", prob_eq)["objective_solved"] is False
    assert evaluate_student_solution("y = 5", prob_eq)["objective_solved"] is False

    prob_expr = {
        "title": "Book Price Expression",
        "expected_steps": ["Answer: 2p + h"],
    }
    assert evaluate_student_solution("2p + h", prob_expr)["objective_solved"] is True
    assert evaluate_student_solution("h + 2p", prob_expr)["objective_solved"] is True
    assert evaluate_student_solution("2p - h", prob_expr)["objective_solved"] is False
    print("   [OK] Algebraic equations and expressions verified.")


def test_exploratory_messages():
    print("\n[TEST 5] Testing Non-Attempt Socratic Questions...")
    prob = {
        "title": "Sticker Packs",
        "expected_steps": ["Answer: 40"],
    }

    hint_req = evaluate_student_solution("Can you give me a hint? What should I do first?", prob)
    assert hint_req["objective_solved"] is False
    assert hint_req["is_explicit_attempt"] is False
    print("   [OK] Exploratory non-attempt questions safely distinguished.")


if __name__ == "__main__":
    test_arithmetic_evaluation()
    test_fraction_and_decimal_equivalence()
    test_mixed_fractions()
    test_algebraic_equations()
    test_exploratory_messages()
    print("\n=== ALL OBJECTIVE MATH EVALUATOR TESTS PASSED! ===")
