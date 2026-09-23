"""
Symbolic CAS & Math Equivalence Benchmark Suite.
Tests 100+ rigorous mathematical assertions across arithmetic, fractions,
algebraic equations, distributive expansions, commutativity, and false-positive intent defenses.
"""
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evaluators.math_evaluator import (
    verify_math_equivalence,
    evaluate_student_solution,
    parse_fraction_or_num,
    normalize_expression,
    extract_expected_answer,
    extract_student_candidate,
)

CAS_TEST_CASES: List[Dict[str, Any]] = [
    # ── Category 1: Fraction & Decimal Equivalence (20 cases) ─────────────────
    {"cand": "3/4", "exp": "3/4", "type": "fraction", "should_match": True},
    {"cand": "6/8", "exp": "3/4", "type": "fraction", "should_match": True},
    {"cand": "9/12", "exp": "3/4", "type": "fraction", "should_match": True},
    {"cand": "0.75", "exp": "3/4", "type": "fraction", "should_match": True},
    {"cand": ".75", "exp": "3/4", "type": "fraction", "should_match": True},
    {"cand": "1/2", "exp": "2/4", "type": "fraction", "should_match": True},
    {"cand": "0.5", "exp": "1/2", "type": "fraction", "should_match": True},
    {"cand": "5/10", "exp": "1/2", "type": "fraction", "should_match": True},
    {"cand": "2/5", "exp": "0.4", "type": "fraction", "should_match": True},
    {"cand": "4/10", "exp": "0.4", "type": "fraction", "should_match": True},
    {"cand": "7/8", "exp": "0.875", "type": "fraction", "should_match": True},
    {"cand": "1/3", "exp": "2/6", "type": "fraction", "should_match": True},
    {"cand": "3/9", "exp": "1/3", "type": "fraction", "should_match": True},
    {"cand": "4/5", "exp": "0.8", "type": "fraction", "should_match": True},
    {"cand": "5/8", "exp": "3/4", "type": "fraction", "should_match": False},
    {"cand": "7/10", "exp": "3/4", "type": "fraction", "should_match": False},
    {"cand": "0.6", "exp": "3/4", "type": "fraction", "should_match": False},
    {"cand": "1/4", "exp": "1/2", "type": "fraction", "should_match": False},
    {"cand": "2/3", "exp": "3/4", "type": "fraction", "should_match": False},
    {"cand": "0.33", "exp": "1/2", "type": "fraction", "should_match": False},

    # ── Category 2: Mixed Fraction Equivalence (15 cases) ─────────────────────
    {"cand": "1 1/2", "exp": "3/2", "type": "fraction", "should_match": True},
    {"cand": "3/2", "exp": "1 1/2", "type": "fraction", "should_match": True},
    {"cand": "1.5", "exp": "1 1/2", "type": "fraction", "should_match": True},
    {"cand": "2 3/4", "exp": "11/4", "type": "fraction", "should_match": True},
    {"cand": "2.75", "exp": "2 3/4", "type": "fraction", "should_match": True},
    {"cand": "1 2/4", "exp": "1 1/2", "type": "fraction", "should_match": True},
    {"cand": "3 1/3", "exp": "10/3", "type": "fraction", "should_match": True},
    {"cand": "4 1/2", "exp": "9/2", "type": "fraction", "should_match": True},
    {"cand": "1 3/8", "exp": "11/8", "type": "fraction", "should_match": True},
    {"cand": "2 1/5", "exp": "11/5", "type": "fraction", "should_match": True},
    {"cand": "2 1/2", "exp": "1 1/2", "type": "fraction", "should_match": False},
    {"cand": "1 1/4", "exp": "1 1/2", "type": "fraction", "should_match": False},
    {"cand": "3 1/2", "exp": "7/4", "type": "fraction", "should_match": False},
    {"cand": "1 1/3", "exp": "5/3", "type": "fraction", "should_match": False},
    {"cand": "2 3/4", "exp": "9/4", "type": "fraction", "should_match": False},

    # ── Category 3: Algebraic Expressions & Commutativity (25 cases) ──────────
    {"cand": "2p + h", "exp": "h + 2p", "type": "expression", "should_match": True},
    {"cand": "h + 2p", "exp": "2p + h", "type": "expression", "should_match": True},
    {"cand": "3x + 5", "exp": "5 + 3x", "type": "expression", "should_match": True},
    {"cand": "-y + 2x", "exp": "2x - y", "type": "expression", "should_match": True},
    {"cand": "2x - y", "exp": "-y + 2x", "type": "expression", "should_match": True},
    {"cand": "4a + 3b", "exp": "3b + 4a", "type": "expression", "should_match": True},
    {"cand": "15 + 4t", "exp": "4t + 15", "type": "expression", "should_match": True},
    {"cand": "n + 7", "exp": "7 + n", "type": "expression", "should_match": True},
    {"cand": "3(x + 2)", "exp": "3x + 6", "type": "expression", "should_match": True},
    {"cand": "3x + 6", "exp": "3(x + 2)", "type": "expression", "should_match": True},
    {"cand": "2(p - 4)", "exp": "2p - 8", "type": "expression", "should_match": True},
    {"cand": "4(2y + 1)", "exp": "8y + 4", "type": "expression", "should_match": True},
    {"cand": "5(a + b)", "exp": "5a + 5b", "type": "expression", "should_match": True},
    {"cand": "9w", "exp": "9w", "type": "expression", "should_match": True},
    {"cand": "x + y + z", "exp": "z + y + x", "type": "expression", "should_match": True},
    {"cand": "2p - h", "exp": "2p + h", "type": "expression", "should_match": False},
    {"cand": "3x + 4", "exp": "3x + 5", "type": "expression", "should_match": False},
    {"cand": "4x - 2", "exp": "2x - 4", "type": "expression", "should_match": False},
    {"cand": "2(x + 3)", "exp": "2x + 5", "type": "expression", "should_match": False},
    {"cand": "5a - 3b", "exp": "3b - 5a", "type": "expression", "should_match": False},
    {"cand": "x + 2", "exp": "2x + 1", "type": "expression", "should_match": False},
    {"cand": "7w", "exp": "9w", "type": "expression", "should_match": False},
    {"cand": "4t + 12", "exp": "4t + 15", "type": "expression", "should_match": False},
    {"cand": "h - 2p", "exp": "2p - h", "type": "expression", "should_match": False},
    {"cand": "3x + 6", "exp": "3x + 9", "type": "expression", "should_match": False},

    # ── Category 4: Equation Equivalence (20 cases) ───────────────────────────
    {"cand": "x = 4", "exp": "x = 4", "type": "equation", "should_match": True},
    {"cand": "4 = x", "exp": "x = 4", "type": "equation", "should_match": True},
    {"cand": "x = 4.0", "exp": "x = 4", "type": "equation", "should_match": True},
    {"cand": "x = 8/2", "exp": "x = 4", "type": "equation", "should_match": True},
    {"cand": "4", "exp": "x = 4", "type": "equation", "should_match": True},
    {"cand": "y = 3/4", "exp": "y = 6/8", "type": "equation", "should_match": True},
    {"cand": "y = 0.75", "exp": "y = 3/4", "type": "equation", "should_match": True},
    {"cand": "a = -5", "exp": "a = -5", "type": "equation", "should_match": True},
    {"cand": "-5 = a", "exp": "a = -5", "type": "equation", "should_match": True},
    {"cand": "p = 1 1/2", "exp": "p = 3/2", "type": "equation", "should_match": True},
    {"cand": "x = 5", "exp": "x = 4", "type": "equation", "should_match": False},
    {"cand": "y = 4", "exp": "x = 4", "type": "equation", "should_match": False},
    {"cand": "x = -4", "exp": "x = 4", "type": "equation", "should_match": False},
    {"cand": "a = 2", "exp": "a = -2", "type": "equation", "should_match": False},
    {"cand": "x = 1/2", "exp": "x = 3/4", "type": "equation", "should_match": False},
    {"cand": "5", "exp": "x = 4", "type": "equation", "should_match": False},
    {"cand": "b = 10", "exp": "b = 20", "type": "equation", "should_match": False},
    {"cand": "z = 0", "exp": "z = 1", "type": "equation", "should_match": False},
    {"cand": "x = 1.25", "exp": "x = 1.5", "type": "equation", "should_match": False},
    {"cand": "w = 3/5", "exp": "w = 4/5", "type": "equation", "should_match": False},

    # ── Category 5: Numeric Integers & Currency / Commas (20 cases) ───────────
    {"cand": "40", "exp": "40", "type": "number", "should_match": True},
    {"cand": "40.0", "exp": "40", "type": "number", "should_match": True},
    {"cand": "1,000", "exp": "1000", "type": "number", "should_match": True},
    {"cand": "1000", "exp": "1,000", "type": "number", "should_match": True},
    {"cand": "25.5", "exp": "25.50", "type": "number", "should_match": True},
    {"cand": "-12", "exp": "-12", "type": "number", "should_match": True},
    {"cand": "0", "exp": "0.0", "type": "number", "should_match": True},
    {"cand": "100", "exp": "100", "type": "number", "should_match": True},
    {"cand": "350", "exp": "350", "type": "number", "should_match": True},
    {"cand": "41.5", "exp": "41.5", "type": "number", "should_match": True},
    {"cand": "20", "exp": "40", "type": "number", "should_match": False},
    {"cand": "100", "exp": "1000", "type": "number", "should_match": False},
    {"cand": "-12", "exp": "12", "type": "number", "should_match": False},
    {"cand": "25.5", "exp": "25.0", "type": "number", "should_match": False},
    {"cand": "39", "exp": "40", "type": "number", "should_match": False},
    {"cand": "40.5", "exp": "40", "type": "number", "should_match": False},
    {"cand": "500", "exp": "50", "type": "number", "should_match": False},
    {"cand": "14", "exp": "24", "type": "number", "should_match": False},
    {"cand": "7", "exp": "8", "type": "number", "should_match": False},
    {"cand": "99", "exp": "100", "type": "number", "should_match": False},
]


def run_cas_benchmark() -> Dict[str, Any]:
    """Execute deterministic CAS and mathematical equivalence suite."""
    print("=" * 76)
    print("   SYMBOLIC CAS & MATHEMATICAL EQUIVALENCE BENCHMARK")
    print(f"   Evaluating {len(CAS_TEST_CASES)} mathematical equivalence test cases")
    print("=" * 76)

    t0 = time.time()
    passed_cases = 0
    failed_cases = 0

    type_stats: Dict[str, Dict[str, int]] = {}

    for item in CAS_TEST_CASES:
        cand = item["cand"]
        exp = item["exp"]
        e_type = item["type"]
        expected_match = item["should_match"]

        if e_type not in type_stats:
            type_stats[e_type] = {"total": 0, "passed": 0, "failed": 0}
        type_stats[e_type]["total"] += 1

        actual_match = verify_math_equivalence(cand, exp, e_type)
        if actual_match == expected_match:
            passed_cases += 1
            type_stats[e_type]["passed"] += 1
        else:
            failed_cases += 1
            type_stats[e_type]["failed"] += 1
            print(f"   [FAIL] cand='{cand}' vs exp='{exp}' ({e_type}): expected {expected_match}, got {actual_match}")

    elapsed = time.time() - t0
    total = len(CAS_TEST_CASES)
    accuracy = (passed_cases / total) * 100 if total > 0 else 0.0

    print(f"\n[BENCHMARK RESULTS - {elapsed:.3f}s]")
    print(f" • Total CAS Cases Tested:      {total}")
    print(f" • Correct Classifications:     {passed_cases}/{total} ({accuracy:.1f}%)")
    print(f" • Mathematical Precision:      {accuracy:.2f}% (Target: 100.0%)")

    print("\n[CATEGORY BREAKDOWN]")
    for e_type, stats in type_stats.items():
        acc = (stats['passed'] / stats['total']) * 100
        print(f" - {e_type:<26}: {stats['passed']}/{stats['total']} passed ({acc:.1f}%)")

    print("-" * 76)

    return {
        "benchmark": "Symbolic CAS Math Equivalence Benchmark",
        "total_cases": total,
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
        "accuracy_pct": round(accuracy, 2),
        "type_breakdown": type_stats,
        "duration_seconds": round(elapsed, 4),
        "passed": (accuracy == 100.0),
    }


if __name__ == "__main__":
    res = run_cas_benchmark()
    sys.exit(0 if res["passed"] else 1)
