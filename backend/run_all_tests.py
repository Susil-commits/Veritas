"""
Veritas Master Test Runner — Runs all verified automated test suites.
Produces a crisp terminal output designed for Demo Day screen recording.
"""
import sys
import subprocess
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
        getattr(sys.stderr, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

BACKEND_DIR = Path(__file__).resolve().parent

TEST_SCRIPTS = [
    ("test_startup_smoke.py", "FastAPI Lifespan & LangGraph State Machine Smoke Test"),
    ("test_auth_p0_parent_isolation.py", "Parent Role Authorization & Isolation (P0)"),
    ("test_math_evaluator.py", "Deterministic Math Evaluator & Intent Parsing"),
    ("test_problem_turn_tracking.py", "Problem Turn Tracking & Attempt Isolation"),
    ("test_session_persistence.py", "Day-3 Resiliency & Session Persistence"),
    ("test_production_rls.py", "Production RLS & Credential Isolation"),
    ("test_safety.py", "Platform Safety & Socratic Guardrails"),
    ("test_auth_and_rag.py", "Student Scoping, Rate Limiting & RAG Retrieval"),
    ("test_parent_child_flow.py", "Parent-Child Architecture & Inactivity Alerts"),
    ("test_neo.py", "Neo AI Platform Assistant & Guardrails"),
    ("test_session_and_score_fixes.py", "Session Resumption & Score Protection"),
    ("test_game_progress_persistence.py", "Math Arcade Games & Relogin Persistence"),
]

def main():
    print("=" * 76)
    print("   VERITAS AI SOCRATIC TUTOR — AUTOMATED VALIDATION SUITE")
    print("=" * 76)
    start_time = time.time()
    results = []

    for script, name in TEST_SCRIPTS:
        print(f"\n▶ Running {name} ({script})...")
        t0 = time.time()
        res = subprocess.run([sys.executable, script], cwd=str(BACKEND_DIR))
        elapsed = time.time() - t0
        passed = (res.returncode == 0)
        results.append({
            "script": script,
            "name": name,
            "passed": passed,
            "duration": elapsed,
            "returncode": res.returncode,
        })
        if passed:
            print(f"  ✓ {name} passed in {elapsed:.2f}s")
        else:
            print(f"  ✗ {name} failed with exit code {res.returncode} in {elapsed:.2f}s")

    total_time = time.time() - start_time
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(TEST_SCRIPTS)
    width = 76

    print("\n" + "=" * width)
    print("APPLICATION TEST EXECUTION SUMMARY".center(width))
    print("=" * width)
    print(f" {'#':<2} | {'TEST SUITE':<47} | {'STATUS':<10} | {'TIME':>7}")
    print("-" * width)
    for i, r in enumerate(results, 1):
        status_str = "✓ PASS" if r["passed"] else f"✗ FAIL ({r['returncode']})"
        print(f" {i:<2} | {r['name']:<47} | {status_str:<10} | {r['duration']:>6.2f}s")
    print("-" * width)

    if passed_count == total_count:
        print(f"  ALL {passed_count}/{total_count} TEST SUITES PASSED IN {total_time:.2f}s!")
        print(f"  STATUS: ALL {total_count} APPLICATION TEST SUITES PASSED")
        print("=" * width + "\n")
        sys.exit(0)
    else:
        failed_count = total_count - passed_count
        print(f"  {passed_count}/{total_count} PASSED, {failed_count}/{total_count} FAILED IN {total_time:.2f}s")
        print("  STATUS: ATTENTION REQUIRED — SOME TEST SUITES FAILED")
        print("=" * width + "\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
