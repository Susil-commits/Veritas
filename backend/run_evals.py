"""
Veritas Master Evaluation CLI Entrypoint.
Run with: python run_evals.py
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
        getattr(sys.stderr, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import os
import argparse
from evals.generate_eval_report import generate_full_evaluation_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Veritas Master Evaluation CLI")
    parser.add_argument("--live", action="store_true", help="Run with live Gemini models")
    parser.add_argument("--mock", action="store_true", help="Run with offline deterministic mock models (default)")
    args = parser.parse_args()

    if args.live:
        os.environ.pop("VERITAS_MOCK_LLM", None)
        os.environ.pop("VERITAS_TEST_MODE", None)
    else:
        os.environ["VERITAS_MOCK_LLM"] = "true"
        os.environ["VERITAS_TEST_MODE"] = "true"

    report = generate_full_evaluation_report()
    passed = (report["metadata"]["overall_status"] == "ALL_BENCHMARKS_PASSED")
    sys.exit(0 if passed else 1)
