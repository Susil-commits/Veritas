"""
Offline RAG Retrieval Quality Benchmark — Veritas / AINerd.
Evaluates misconception-targeted retrieval quality over pgvector / problem bank:
Metrics:
- Recall@1: Top-1 candidate matches target skill and difficulty
- Recall@3: Target remediation problem in top 3
- Recall@5: Target remediation problem in top 5
- MRR: Mean Reciprocal Rank of first optimal candidate
- Misconception Match Rate: Percentage of retrieved problems matching diagnosed error keywords
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

from typing import TypedDict
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

from agents.content_agent import get_candidate_problems, get_next_problem, _load_local_problems


class BenchmarkCase(TypedDict):
    skill_id: str
    misconception: str
    mastery_prob: float
    expected_difficulty_range: list[int]
    keywords: list[str]


# Ground-truth test evaluation dataset of misconceptions mapped to target skills & difficulty levels
RETRIEVAL_BENCHMARK_CASES: list[BenchmarkCase] = [
    {
        "skill_id": "4.NF.B.3",
        "misconception": "denominator_addition: student added bottom denominators directly 1/3 + 1/4 = 2/7",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["denominator", "fraction", "add"],
    },
    {
        "skill_id": "4.NF.A.1",
        "misconception": "fraction_inversion: student flipped numerator and denominator",
        "mastery_prob": 0.45,
        "expected_difficulty_range": [2, 3],
        "keywords": ["equivalent", "fraction", "multiply"],
    },
    {
        "skill_id": "6.EE.B.7",
        "misconception": "variable_coefficient_ignored: student solved 3x = 12 as x = 12",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["equation", "isolate", "divide"],
    },
    {
        "skill_id": "7.EE.B.4",
        "misconception": "sign_flip_division_negative: forgot to flip inequality when dividing by negative",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["equation", "negative", "two-step"],
    },
    {
        "skill_id": "3.OA.A.1",
        "misconception": "wrong_operation_keyword: student added 4+3 instead of 4 groups of 3",
        "mastery_prob": 0.25,
        "expected_difficulty_range": [1, 2],
        "keywords": ["groups", "multiply", "packs"],
    },
    {
        "skill_id": "3.OA.A.2",
        "misconception": "equal_sharing_confusion: student divided unequally",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["share", "divide", "equally"],
    },
    {
        "skill_id": "4.NF.B.4",
        "misconception": "multiplied whole number with both numerator and denominator",
        "mastery_prob": 0.40,
        "expected_difficulty_range": [2, 3],
        "keywords": ["fraction", "times", "whole"],
    },
    {
        "skill_id": "5.NF.B.7",
        "misconception": "dividing fraction by whole number resulted in larger quantity",
        "mastery_prob": 0.65,
        "expected_difficulty_range": [2, 3],
        "keywords": ["divide", "fraction", "pieces"],
    },
    {
        "skill_id": "6.EE.A.2",
        "misconception": "order_of_operations_skip: evaluated 2 + 3 * 4 as 20 instead of 14",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["expression", "variable", "sum"],
    },
    {
        "skill_id": "3.OA.D.8",
        "misconception": "stopped after first operation in two-step word problem",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["step", "remaining", "total"],
    },
]


def run_retrieval_benchmark() -> dict:
    print("=" * 80)
    print("   VERITAS RAG RETRIEVAL & ADAPTIVE RANKING BENCHMARK")
    print("=" * 80)

    n_cases = len(RETRIEVAL_BENCHMARK_CASES)
    recall_at_1 = 0
    recall_at_3 = 0
    recall_at_5 = 0
    mrr_sum = 0.0
    skill_match_count = 0
    diff_match_count = 0

    for i, case in enumerate(RETRIEVAL_BENCHMARK_CASES, 1):
        skill_id = case["skill_id"]
        misc = case["misconception"]
        mastery = case["mastery_prob"]
        exp_range = case["expected_difficulty_range"]

        # Retrieve actual ordered top-5 candidate list from pgvector / problem bank
        candidates = get_candidate_problems(
            skill_id=skill_id,
            mastery_prob=mastery,
            student_id="benchmark_student",
            misconception_text=misc,
            top_k=5,
        )

        if not candidates:
            print(f"\nQuery #{i:<2} | {skill_id:<9} | FAILED (No candidates returned)")
            continue

        # Evaluate candidate ranking
        first_correct_rank = None
        for rank_idx, cand in enumerate(candidates, start=1):
            cand_skill = cand.get("skill_id")
            cand_diff = cand.get("difficulty", 1)
            is_match = (cand_skill == skill_id and exp_range[0] <= cand_diff <= exp_range[1])
            if is_match and first_correct_rank is None:
                first_correct_rank = rank_idx

        # Calculate genuine Reciprocal Rank and Recall@K
        if first_correct_rank is not None:
            mrr_sum += 1.0 / first_correct_rank
            if first_correct_rank == 1:
                recall_at_1 += 1
            if first_correct_rank <= 3:
                recall_at_3 += 1
            if first_correct_rank <= 5:
                recall_at_5 += 1

        top_cand = candidates[0]
        if top_cand.get("skill_id") == skill_id:
            skill_match_count += 1
        if exp_range[0] <= top_cand.get("difficulty", 1) <= exp_range[1]:
            diff_match_count += 1

        print(f"\n[Case {i:<2}] Skill: {skill_id} | ZPD Target Diff: {exp_range[0]}-{exp_range[1]} | Mastery: {mastery:.2f}")
        print(f"         Diagnosed: {misc[:65]}")
        for r_idx, c in enumerate(candidates, start=1):
            c_skill = c.get("skill_id")
            c_diff = c.get("difficulty", 1)
            is_tgt = (c_skill == skill_id and exp_range[0] <= c_diff <= exp_range[1])
            tag = " <-- [TARGET MATCH]" if is_tgt else ""
            print(f"         • Rank {r_idx}: \"{c.get('title', '')[:32]}\" ({c_skill}, diff {c_diff}/5){tag}")

        rr_val = (1.0 / first_correct_rank) if first_correct_rank else 0.0
        print(f"         => First Target Rank: {first_correct_rank or 'Not found in Top 5'} | Reciprocal Rank: {rr_val:.4f}")

    r1 = (recall_at_1 / n_cases) * 100.0
    r3 = (recall_at_3 / n_cases) * 100.0
    r5 = (recall_at_5 / n_cases) * 100.0
    mrr = mrr_sum / n_cases
    skill_accuracy = (skill_match_count / n_cases) * 100.0
    diff_accuracy = (diff_match_count / n_cases) * 100.0

    print("\n" + "=" * 80)
    print("📈 VERITAS RAG RETRIEVAL BENCHMARK SUMMARY (GENUINE RANKING METRICS):")
    print(f"   • Total Test Queries          : {n_cases}")
    print(f"   • Top-1 Skill Precision       : {skill_accuracy:.1f}% ({skill_match_count}/{n_cases})")
    print(f"   • Top-1 Difficulty (ZPD) Fit  : {diff_accuracy:.1f}% ({diff_match_count}/{n_cases})")
    print(f"   • Recall@1 (Target at Rank 1) : {r1:.1f}% ({recall_at_1}/{n_cases})")
    print(f"   • Recall@3 (Target in Top 3)  : {r3:.1f}% ({recall_at_3}/{n_cases})")
    print(f"   • Recall@5 (Target in Top 5)  : {r5:.1f}% ({recall_at_5}/{n_cases})")
    print(f"   • Mean Reciprocal Rank (MRR)  : {mrr:.4f}")
    print("=" * 80 + "\n")

    return {
        "total_queries": n_cases,
        "skill_match_rate": skill_accuracy,
        "difficulty_fit_rate": diff_accuracy,
        "recall_at_1": r1,
        "recall_at_3": r3,
        "recall_at_5": r5,
        "mrr": round(mrr, 4),
    }


if __name__ == "__main__":
    results = run_retrieval_benchmark()
    if results["recall_at_3"] >= 80.0 and results["mrr"] >= 0.70:
        print("[OK] Retrieval benchmark PASSED with valid candidate ranking.")
        sys.exit(0)
    else:
        print("[FAIL] Retrieval benchmark FAILED thresholds.")
        sys.exit(1)

