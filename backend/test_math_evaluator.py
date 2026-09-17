"""
Unit tests for Deterministic Objective Math Evaluator.
Verifies arithmetic, fractions, equations, expressions, and incorrect answer rejection.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluators.math_evaluator import (
    evaluate_student_solution,
    verify_math_equivalence,
    extract_expected_answer,
)


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

    # Regression Case 1: 2p + h (classified as expression, not bare digit '2')
    prob_expr = {
        "title": "Book Price Expression",
        "expected_steps": ["Answer: 2p + h"],
    }
    ans_str, ans_type = extract_expected_answer(prob_expr)
    assert ans_type == "expression", f"Expected 'expression', got {ans_type}"
    assert ans_str == "2p + h", f"Expected '2p + h', got {ans_str}"
    assert evaluate_student_solution("2p + h", prob_expr)["objective_solved"] is True
    assert evaluate_student_solution("h + 2p", prob_expr)["objective_solved"] is True
    assert evaluate_student_solution("2p - h", prob_expr)["objective_solved"] is False
    assert evaluate_student_solution("2", prob_expr)["objective_solved"] is False, "Bare number 2 must not satisfy '2p + h'"

    # Regression Case 2: h + 2p (commutative ordering)
    prob_expr_rev = {
        "title": "Commutative Expression",
        "expected_steps": ["Answer: h + 2p"],
    }
    ans_rev, type_rev = extract_expected_answer(prob_expr_rev)
    assert type_rev == "expression", f"Expected 'expression', got {type_rev}"
    assert ans_rev == "h + 2p", f"Expected 'h + 2p', got {ans_rev}"
    assert evaluate_student_solution("h + 2p", prob_expr_rev)["objective_solved"] is True
    assert evaluate_student_solution("2p + h", prob_expr_rev)["objective_solved"] is True

    # Regression Case 3: 2p - h (non-commutative subtraction)
    prob_expr_diff = {
        "title": "Difference Expression",
        "expected_steps": ["Answer: 2p - h"],
    }
    ans_diff, type_diff = extract_expected_answer(prob_expr_diff)
    assert type_diff == "expression", f"Expected 'expression', got {type_diff}"
    assert ans_diff == "2p - h", f"Expected '2p - h', got {ans_diff}"
    assert evaluate_student_solution("2p - h", prob_expr_diff)["objective_solved"] is True
    assert evaluate_student_solution("2p + h", prob_expr_diff)["objective_solved"] is False
    assert evaluate_student_solution("h - 2p", prob_expr_diff)["objective_solved"] is False

    # Regression Case 4: Expression with constant prefix e.g. 15 + 4t (classified as expression, not '15')
    prob_const_expr = {
        "title": "Admission with Ride Tickets",
        "expected_steps": ["Answer: 15 + 4t"],
    }
    ans_const, type_const = extract_expected_answer(prob_const_expr)
    assert type_const == "expression", f"Expected 'expression', got {type_const}"
    assert ans_const == "15 + 4t", f"Expected '15 + 4t', got {ans_const}"
    assert evaluate_student_solution("15 + 4t", prob_const_expr)["objective_solved"] is True
    assert evaluate_student_solution("4t + 15", prob_const_expr)["objective_solved"] is True
    assert evaluate_student_solution("15", prob_const_expr)["objective_solved"] is False, "Bare number 15 must not satisfy '15 + 4t'"

    # Regression Case 5: Single variable with coefficient e.g. 9w
    prob_single_var = {
        "title": "Single Variable Term",
        "expected_steps": ["Answer: 9w"],
    }
    ans_single, type_single = extract_expected_answer(prob_single_var)
    assert type_single == "expression", f"Expected 'expression', got {type_single}"
    assert ans_single == "9w", f"Expected '9w', got {ans_single}"
    assert evaluate_student_solution("9w", prob_single_var)["objective_solved"] is True
    assert evaluate_student_solution("9", prob_single_var)["objective_solved"] is False, "Bare number 9 must not satisfy '9w'"

    print("   [OK] Algebraic equations and expressions verified (2p+h, h+2p, 2p-h, 15+4t, 9w).")


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


def test_attempt_type_differentiation():
    print("\n[TEST 6] Testing Pedagogical Attempt-Type Differentiation in BKT...")
    from bkt.tracker import update_mastery

    initial_m = 0.30
    skill_id = "4.NF.B.3"

    m_independent = update_mastery(initial_m, True, skill_id, attempt_type="independent_attempt")
    m_corrected = update_mastery(initial_m, True, skill_id, attempt_type="corrected_after_feedback")
    m_hinted = update_mastery(initial_m, True, skill_id, attempt_type="hinted_attempt")

    assert m_independent > initial_m, "Independent correct attempt must increase mastery"
    assert m_corrected > initial_m, "Corrected after feedback must increase mastery"
    assert m_hinted > initial_m, "Hinted correct attempt must increase mastery"
    assert m_independent > m_corrected, f"Independent ({m_independent}) should exceed corrected ({m_corrected})"
    print(f"   [OK] Attempt types verified: Independent={m_independent*100:.1f}%, Hinted={m_hinted*100:.1f}%, Corrected={m_corrected*100:.1f}%.")


def test_false_positive_adversarial_defense():
    print("\n[TEST 7] Testing False-Positive Defenses (Negation, Disjunction, Contextual Numbers)...")
    prob_12 = {
        "title": "Apple Basket",
        "expected_steps": ["Answer: 12"],
    }
    prob_8 = {
        "title": "Apple Basket",
        "expected_steps": ["Answer: 8"],
    }

    # Case A: Negated candidate + contextual problem number: "I think the answer isn't 12, maybe 8. The problem gives 12 apples."
    adversarial_msg = "I think the answer isn't 12, maybe 8. The problem gives 12 apples."
    res_for_12 = evaluate_student_solution(adversarial_msg, prob_12)
    assert res_for_12["objective_solved"] is False, f"False positive! Negated 12 was marked correct: {res_for_12}"
    print("   [OK] Negated candidate 'isn't 12' and contextual '12 apples' rejected for expected 12.")

    res_for_8 = evaluate_student_solution(adversarial_msg, prob_8)
    assert res_for_8["objective_solved"] is True, f"Positive candidate 'maybe 8' failed to resolve: {res_for_8}"
    print("   [OK] Positive intent 'maybe 8' correctly resolved for expected 8.")

    # Case B: Disjunctive undecided query: "Is the answer 12 or 15?"
    disjunctive_msg = "Is the answer 12 or 15?"
    res_disj = evaluate_student_solution(disjunctive_msg, prob_12)
    assert res_disj["objective_solved"] is False, f"False positive! Disjunctive query marked correct: {res_disj}"
    assert res_disj["is_explicit_attempt"] is False
    print("   [OK] Disjunctive undecided query '12 or 15' rejected as non-attempt.")

    # Case C: Contextual mention without answer intent in long sentence:
    # "The question says 40 students are in the room, what formula should I use?" with expected answer 40
    prob_40 = {
        "title": "Room Count",
        "expected_steps": ["Answer: 40"],
    }
    context_msg = "The question says 40 students are in the room, what formula should I use?"
    res_context = evaluate_student_solution(context_msg, prob_40)
    assert res_context["objective_solved"] is False, f"False positive! Contextual question marked correct: {res_context}"
    print("   [OK] Contextual mention in long query rejected without answer intent.")


if __name__ == "__main__":
    test_arithmetic_evaluation()
    test_fraction_and_decimal_equivalence()
    test_mixed_fractions()
    test_algebraic_equations()
    test_exploratory_messages()
    test_attempt_type_differentiation()
    test_false_positive_adversarial_defense()
    print("\n=== ALL OBJECTIVE MATH EVALUATOR TESTS PASSED! ===")

