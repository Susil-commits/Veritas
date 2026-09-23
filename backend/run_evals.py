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

from evals.generate_eval_report import generate_full_evaluation_report

if __name__ == "__main__":
    report = generate_full_evaluation_report()
    passed = (report["metadata"]["overall_status"] == "ALL_BENCHMARKS_PASSED")
    sys.exit(0 if passed else 1)
