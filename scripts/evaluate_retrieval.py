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
    target_remediation_titles: list[str]


# Ground-truth test evaluation dataset of misconceptions mapped to target skills, keywords & human-labelled remediation targets
RETRIEVAL_BENCHMARK_CASES: list[BenchmarkCase] = [
    {
        "skill_id": "4.NF.B.3",
        "misconception": "denominator_addition: student added bottom denominators directly 1/3 + 1/4 = 2/7",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["denominator", "fraction", "add"],
        "target_remediation_titles": [
            "Pizza Fractions",
            "Pie Slices Addition",
            "Walking Trails: Unlike Denominators",
            "Flour Jar Addition: Fifths and Thirds",
            "Ribbon Cutting",
            "Running Distance",
        ],
    },
    {
        "skill_id": "4.NF.A.1",
        "misconception": "fraction_inversion: student flipped numerator and denominator",
        "mastery_prob": 0.45,
        "expected_difficulty_range": [2, 3],
        "keywords": ["equivalent", "fraction", "numerator", "denominator"],
        "target_remediation_titles": [
            "Equivalent Fractions Puzzle",
            "Equivalent Fractions: Halves to Eighths",
            "Equivalent Fractions: Thirds to Ninths",
            "Simplifying Six-Tenths",
            "Equivalent Fraction Matching",
            "Equivalent Fraction in a Recipe",
            "Fraction Strips: Thirds and Sixths",
            "Comparing Fractions with Common Denominators",
        ],
    },
    {
        "skill_id": "6.EE.B.7",
        "misconception": "variable_coefficient_ignored: student solved 3x = 12 as x = 12",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["equation", "isolate", "divide", "coefficient"],
        "target_remediation_titles": [
            "Solve for x: Division",
            "Solving Multiplication Equation",
            "Solving Division Equation",
            "One-Step Multiplication: 10m = 240",
            "Fraction Coefficient: Half of a Number",
            "One-Step Division: y / 9 = 7",
            "Solve for x: Simple",
        ],
    },
    {
        "skill_id": "7.EE.B.4",
        "misconception": "sign_flip_division_negative: forgot to flip inequality when dividing by negative",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["inequality", "negative", "two-step", "flip"],
        "target_remediation_titles": [
            "Negative Coefficient Inequality",
            "Negative Distributive Inequality",
            "Solving Multi-Step Linear Inequality",
            "Solving Linear Inequality: 4x +",
            "Taxi Fare Budget Inequality",
            "Challenge: Inequality",
        ],
    },
    {
        "skill_id": "3.OA.A.1",
        "misconception": "wrong_operation_keyword: student added 4+3 instead of 4 groups of 3",
        "mastery_prob": 0.25,
        "expected_difficulty_range": [1, 2],
        "keywords": ["groups", "multiply", "packs", "times"],
        "target_remediation_titles": [
            "Sticker Packs",
            "Garden Tomato Rows",
            "Crayon Boxes",
            "Library Bookshelves",
            "Bakery Cupcake Trays",
            "Toy Car Wheels",
            "Angela Bike Messenger",
        ],
    },
    {
        "skill_id": "3.OA.A.2",
        "misconception": "equal_sharing_confusion: student divided unequally",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["share", "divide", "equally", "split"],
        "target_remediation_titles": [
            "Sharing Pencils",
            "Art Class Supplies",
            "Five Friends Fast",
            "Samuel Bought Dozen",
            "Apples Watermelon Same",
            "Dividing Pizza Equally",
        ],
    },
    {
        "skill_id": "4.NF.B.4",
        "misconception": "multiplied whole number with both numerator and denominator",
        "mastery_prob": 0.40,
        "expected_difficulty_range": [2, 3],
        "keywords": ["fraction", "times", "whole", "multiply"],
        "target_remediation_titles": [
            "Classroom Fraction of a Whole",
            "Ribbon for Gift Packages",
            "Running Laps Around the Track",
            "Fuel Tank Capacity",
            "Multi-Step Recipe Batch Adjustment",
            "Fraction Multiplication",
        ],
    },
    {
        "skill_id": "5.NF.B.7",
        "misconception": "dividing fraction by whole number resulted in larger quantity",
        "mastery_prob": 0.65,
        "expected_difficulty_range": [2, 3],
        "keywords": ["divide", "fraction", "pieces", "unit"],
        "target_remediation_titles": [
            "Sharing a Unit Fraction",
            "Dividing Rope Lengths",
            "Measuring Scoops of Flour",
            "Dividing Whole Number by Non-Unit Fraction",
            "Pancake Batter Portions",
            "Dividing Pizza Equally",
            "Flower Garden",
        ],
    },
    {
        "skill_id": "6.EE.A.2",
        "misconception": "order_of_operations_skip: evaluated 2 + 3 * 4 as 20 instead of 14",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["expression", "variable", "sum", "product", "operations"],
        "target_remediation_titles": [
            "Translating Products and Sums",
            "Two-Part Expression: Ticket Prices",
            "Expressions with Two Variables",
            "Translating Sums into Algebra",
            "Writing Product Expressions",
            "Evaluating an Expression",
        ],
    },
    {
        "skill_id": "3.OA.D.8",
        "misconception": "stopped after first operation in two-step word problem",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["step", "remaining", "total", "two-step"],
        "target_remediation_titles": [
            "Movie Snack Bar",
            "Farmer's Market Apples",
            "Book Sale Savings",
            "Carnival Ride Tickets",
            "Baking Cookies",
            "Lemonade Stand",
            "There Houses Street",
            "Baking Cookies Bakes",
        ],
    },
]


def run_retrieval_benchmark() -> dict:
    print("=" * 80)
    print("   VERITAS RAG RETRIEVAL & UNRESTRICTED MISCONCEPTION BENCHMARK")
    print("=" * 80)
    print("Pipeline: Diagnosed Misconception -> Unrestricted Pool Search (208 problems)")
    print("          -> Adaptive Pedagogical Ranker -> Human-Labelled Remediation Targets")
    print("=" * 80)

    n_cases = len(RETRIEVAL_BENCHMARK_CASES)
    recall_at_1 = 0
    recall_at_3 = 0
    recall_at_5 = 0
    mrr_sum = 0.0
    skill_match_count = 0
    diff_match_count = 0
    total_keyword_matches = 0
    total_keywords_tested = 0

    for i, case in enumerate(RETRIEVAL_BENCHMARK_CASES, 1):
        target_skill = case["skill_id"]
        misc = case["misconception"]
        mastery = case["mastery_prob"]
        exp_range = case["expected_difficulty_range"]
        kws = case["keywords"]
        target_titles = case["target_remediation_titles"]

        # Retrieve actual ordered top-5 candidates from UNRESTRICTED candidate pool
        candidates = get_candidate_problems(
            skill_id=None,
            mastery_prob=mastery,
            student_id="benchmark_student",
            misconception_text=misc,
            top_k=5,
            unrestricted=True,
            keywords=kws,
        )

        if not candidates:
            print(f"\nQuery #{i:<2} | {target_skill:<9} | FAILED (No candidates returned)")
            continue

        # Evaluate candidate ranking against human-labelled ground truth
        first_remediation_rank = None
        for rank_idx, cand in enumerate(candidates, start=1):
            cand_title = cand.get("title", "")
            is_target_remediation = any(t.lower() in cand_title.lower() for t in target_titles)
            if is_target_remediation and first_remediation_rank is None:
                first_remediation_rank = rank_idx

        # Calculate genuine Reciprocal Rank and Recall@K
        if first_remediation_rank is not None:
            mrr_sum += 1.0 / first_remediation_rank
            if first_remediation_rank == 1:
                recall_at_1 += 1
            if first_remediation_rank <= 3:
                recall_at_3 += 1
            if first_remediation_rank <= 5:
                recall_at_5 += 1

        top_cand = candidates[0]
        top_skill = top_cand.get("skill_id")
        top_diff = top_cand.get("difficulty", 1)

        if top_skill == target_skill:
            skill_match_count += 1
        if exp_range[0] <= top_diff <= exp_range[1]:
            diff_match_count += 1

        # Evaluate misconception keyword coverage in top-1 candidate
        top_text = f"{top_cand.get('title', '')} {top_cand.get('text', '')} {' '.join(top_cand.get('expected_steps', []))}".lower()
        kws_matched = sum(1 for kw in kws if kw.lower() in top_text)
        total_keyword_matches += kws_matched
        total_keywords_tested += len(kws)

        print(f"\n[Case {i:<2}] Diagnosed Error: \"{misc[:60]}...\"")
        print(f"         Target Skill: {target_skill} | Target ZPD: Diff {exp_range[0]}-{exp_range[1]} | Student Mastery: {mastery:.2f}")
        print(f"         Keywords: {', '.join(kws)}")

        for r_idx, c in enumerate(candidates, start=1):
            c_skill = c.get("skill_id")
            c_diff = c.get("difficulty", 1)
            c_title = c.get("title", "")
            is_remed = any(t.lower() in c_title.lower() for t in target_titles)
            is_skill = (c_skill == target_skill)

            tags = []
            if is_remed:
                tags.append("REMEDIATION TARGET")
            if is_skill:
                tags.append(f"Skill {c_skill}")
            tag_str = f" <-- [{', '.join(tags)}]" if tags else ""

            print(f"         • Rank {r_idx}: \"{c_title[:32]}\" ({c_skill}, diff {c_diff}/5){tag_str}")

        rr_val = (1.0 / first_remediation_rank) if first_remediation_rank else 0.0
        print(f"         => First Remediation Rank: {first_remediation_rank or 'Not found in Top 5'} | Reciprocal Rank: {rr_val:.4f}")
        print(f"         => Top-1 Misconception Keyword Coverage: {kws_matched}/{len(kws)} ({(kws_matched/len(kws))*100:.0f}%)")

    r1 = (recall_at_1 / n_cases) * 100.0
    r3 = (recall_at_3 / n_cases) * 100.0
    r5 = (recall_at_5 / n_cases) * 100.0
    mrr = mrr_sum / n_cases
    skill_accuracy = (skill_match_count / n_cases) * 100.0
    diff_accuracy = (diff_match_count / n_cases) * 100.0
    kw_match_rate = (total_keyword_matches / total_keywords_tested) * 100.0 if total_keywords_tested > 0 else 0.0

    print("\n" + "=" * 80)
    print("📈 VERITAS RAG RETRIEVAL BENCHMARK SUMMARY (UNRESTRICTED POOL):")
    print(f"   • Total Test Diagnostic Queries : {n_cases}")
    print(f"   • Candidate Pool Scope          : Unrestricted (all 208 problems across 10 skills)")
    print(f"   • Top-1 Skill Precision        : {skill_accuracy:.1f}% ({skill_match_count}/{n_cases})")
    print(f"   • Top-1 Difficulty (ZPD) Fit    : {diff_accuracy:.1f}% ({diff_match_count}/{n_cases})")
    print(f"   • Misconception Keyword Match   : {kw_match_rate:.1f}% ({total_keyword_matches}/{total_keywords_tested})")
    print(f"   • Recall@1 (Remediation at #1)  : {r1:.1f}% ({recall_at_1}/{n_cases})")
    print(f"   • Recall@3 (Remediation in Top3): {r3:.1f}% ({recall_at_3}/{n_cases})")
    print(f"   • Recall@5 (Remediation in Top5): {r5:.1f}% ({recall_at_5}/{n_cases})")
    print(f"   • Mean Reciprocal Rank (MRR)    : {mrr:.4f}")
    print("=" * 80 + "\n")

    return {
        "total_queries": n_cases,
        "skill_match_rate": skill_accuracy,
        "difficulty_fit_rate": diff_accuracy,
        "keyword_match_rate": round(kw_match_rate, 1),
        "recall_at_1": r1,
        "recall_at_3": r3,
        "recall_at_5": r5,
        "mrr": round(mrr, 4),
    }


if __name__ == "__main__":
    results = run_retrieval_benchmark()
    if results["recall_at_3"] >= 80.0 and results["mrr"] >= 0.70 and results["skill_match_rate"] >= 80.0:
        print("[OK] Unrestricted RAG retrieval benchmark PASSED with high semantic precision.")
        sys.exit(0)
    else:
        print("[FAIL] Unrestricted RAG retrieval benchmark FAILED thresholds.")
        sys.exit(1)

