"""
Unit Test Suite for Veritas Offline Evaluation Harness & Cognitive DAG Model.
Verifies:
1. Prerequisite DAG knowledge graph relationships & recursive root-deficit diagnosis
2. Ebbinghaus exponential memory forgetting curve decay calculations
3. Automated offline benchmark execution and benchmark_report.json generation
"""
import sys
import os
import json
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

from bkt.tracker import (
    get_skill_prerequisites,
    get_prerequisite_graph,
    apply_time_decay,
    diagnose_root_skill_deficit,
    get_skill_params,
)
from evals.cas_math_benchmark import run_cas_benchmark
from evals.vision_reticle_benchmark import run_vision_reticle_benchmark, compute_box_iou
from evals.generate_eval_report import generate_full_evaluation_report, REPORT_PATH


def test_cognitive_dag_and_prerequisites():
    print("\n[TEST 1] Testing Cognitive Prerequisite Knowledge Graph (DAG)...")
    graph = get_prerequisite_graph()
    assert len(graph) == 10, f"Expected 10 skills in DAG, got {len(graph)}"
    
    # 4.NF.B.3 requires 4.NF.A.1
    prereqs_4nf = get_skill_prerequisites("4.NF.B.3")
    assert "4.NF.A.1" in prereqs_4nf, f"4.NF.B.3 must require 4.NF.A.1, got {prereqs_4nf}"

    # 7.EE.B.4 requires 6.EE.B.7 and 4.NF.B.3
    prereqs_7ee = get_skill_prerequisites("7.EE.B.4")
    assert "6.EE.B.7" in prereqs_7ee and "4.NF.B.3" in prereqs_7ee

    print("   ✓ Prerequisite DAG integrity verified across 10 CCSS standards.")


def test_ebbinghaus_forgetting_decay():
    print("\n[TEST 2] Testing Ebbinghaus Exponential Memory Decay...")
    skill_id = "4.NF.B.3"
    initial_mastery = 0.85
    prior = get_skill_params(skill_id)["prior"]

    # 0 days elapsed -> no change
    decay_0 = apply_time_decay(initial_mastery, 0, skill_id)
    assert decay_0 == initial_mastery

    # 14 days elapsed -> mastery decays towards prior
    decay_14 = apply_time_decay(initial_mastery, 14, skill_id)
    assert decay_14 < initial_mastery
    assert decay_14 >= prior, f"Decayed mastery {decay_14} must not fall below cognitive prior {prior}"

    # Infinite elapsed time -> converges to prior
    decay_365 = apply_time_decay(initial_mastery, 365, skill_id)
    assert abs(decay_365 - prior) <= 0.05, f"Long-term decay should approach prior {prior}, got {decay_365}"

    print(f"   ✓ Ebbinghaus memory curve verified: 0d={decay_0}, 14d={decay_14}, 365d={decay_365}")


def test_root_deficit_diagnostic_traversal():
    print("\n[TEST 3] Testing Recursive Root Deficit Diagnosis...")
    # Student struggling with Adding Fractions (4.NF.B.3), but has deficit in Equivalent Fractions (4.NF.A.1)
    mock_mastery = {
        "3.OA.A.1": 0.90,
        "3.OA.A.2": 0.90,
        "4.NF.A.1": 0.35, # Unmastered prerequisite
        "4.NF.B.3": 0.40,
    }
    root = diagnose_root_skill_deficit(mock_mastery, "4.NF.B.3", mastery_threshold=0.65)
    assert root == "4.NF.A.1", f"Expected root deficit 4.NF.A.1, got {root}"

    # If all prerequisites are sound
    sound_mastery = {
        "3.OA.A.1": 0.90,
        "3.OA.A.2": 0.90,
        "4.NF.A.1": 0.85,
        "4.NF.B.3": 0.40,
    }
    no_root = diagnose_root_skill_deficit(sound_mastery, "4.NF.B.3", mastery_threshold=0.65)
    assert no_root is None, f"Expected None when all prerequisites mastered, got {no_root}"

    print("   ✓ Backward DAG traversal successfully diagnosed root pedagogical deficits.")


def test_offline_eval_harness():
    print("\n[TEST 4] Testing Offline Evaluation Benchmark Harness & Report Generation...")
    report = generate_full_evaluation_report()
    assert report["metadata"]["overall_status"] == "ALL_BENCHMARKS_PASSED"
    assert report["summary_metrics"]["answer_leakage_rate_pct"] == 0.0
    assert report["summary_metrics"]["symbolic_cas_precision_pct"] == 100.0
    assert report["summary_metrics"]["scratchpad_bounding_box_mean_iou"] >= 0.70
    assert REPORT_PATH.exists(), f"Expected report at {REPORT_PATH}"

    print("   ✓ Master evaluation harness executed and verified benchmark_report.json.")


if __name__ == "__main__":
    print("=" * 76)
    print("   VERITAS COGNITIVE DAG & OFFLINE EVALS VERIFICATION SUITE")
    print("=" * 76)
    test_cognitive_dag_and_prerequisites()
    test_ebbinghaus_forgetting_decay()
    test_root_deficit_diagnostic_traversal()
    test_offline_eval_harness()
    print("\n🎉 ALL COGNITIVE DAG & OFFLINE EVALUATION TESTS PASSED WITH 100% SUCCESS!\n")
    sys.exit(0)
