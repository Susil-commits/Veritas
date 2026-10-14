"""
Offline RAG Retrieval Quality Benchmark — Veritas.
Evaluates misconception-targeted retrieval quality over pgvector / problem bank:
Metrics:
- Recall@1: Top-1 candidate matches target remediation problem
- Recall@3: Target remediation problem in top 3
- Recall@5: Target remediation problem in top 5
- MRR: Mean Reciprocal Rank of first optimal candidate
- Top-1 Skill Precision: Percentage of top-1 candidates matching CCSS skill standard
- Top-1 Difficulty (ZPD) Fit: Percentage of top-1 candidates inside student ZPD zone
- Misconception Keyword Coverage: Percentage of diagnosed misconception keywords in top-1 problem

Supports comparative evaluation:
- pgvector mode (dense 768-dim cosine similarity embeddings)
- lexical mode (BM25 / token matching keyword similarity fallback)
Prints sample count (n=...) alongside EVERY metric.
"""
import os
import sys
import json
import argparse
from pathlib import Path
from typing import TypedDict

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

from agents.content_agent import get_candidate_problems


class BenchmarkCase(TypedDict):
    case_id: int
    skill_id: str
    misconception: str
    mastery_prob: float
    expected_difficulty_range: list[int]
    keywords: list[str]
    target_remediation_titles: list[str]


# 40 Ground-Truth Labelled Benchmark Cases (4 cases per CCSS standard across all 10 curriculum standards)
RETRIEVAL_BENCHMARK_CASES: list[BenchmarkCase] = [
    # ── 1. CCSS 3.OA.A.1: Multiplication Concepts & Equal Groups ─────────────
    {
        "case_id": 1,
        "skill_id": "3.OA.A.1",
        "misconception": "additive_reasoning_for_multiplication: student added 4+3 instead of calculating 4 groups of 3",
        "mastery_prob": 0.25,
        "expected_difficulty_range": [1, 2],
        "keywords": ["groups", "multiply", "packs", "times"],
        "target_remediation_titles": [
            "Sticker Packs",
            "Garden Tomato Rows",
            "Crayon Boxes",
            "Bakery Cupcake Trays",
            "Library Bookshelves",
        ],
    },
    {
        "case_id": 2,
        "skill_id": "3.OA.A.1",
        "misconception": "array_dimension_confusion: confused number of rows with items per row when counting grid",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["rows", "plants", "tomato", "garden", "array"],
        "target_remediation_titles": [
            "Garden Tomato Rows",
            "Bakery Cupcake Trays",
            "Library Bookshelves",
            "Crayon Boxes",
        ],
    },
    {
        "case_id": 3,
        "skill_id": "3.OA.A.1",
        "misconception": "unit_group_size_neglect: multiplied total groups without accounting for items per unit",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["wheels", "cars", "produce", "multiply", "items"],
        "target_remediation_titles": [
            "Toy Car Wheels",
            "Soccer Team Jerseys",
            "Bakery Cupcake Trays",
            "Library Bookshelves",
        ],
    },
    {
        "case_id": 4,
        "skill_id": "3.OA.A.1",
        "misconception": "multi_digit_factor_scaling: struggled to scale large multi-digit array products",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["rows", "tiles", "panels", "orchard", "harvest"],
        "target_remediation_titles": [
            "Tile Floor Pattern",
            "Solar Array Panel Output",
            "Orchard Fruit Harvest",
            "Stadium Seating Section Challenge",
        ],
    },

    # ── 2. CCSS 3.OA.A.2: Division Concepts & Equal Partitioning ─────────────
    {
        "case_id": 5,
        "skill_id": "3.OA.A.2",
        "misconception": "equal_sharing_confusion: student divided unequally without partitioning into identical subsets",
        "mastery_prob": 0.25,
        "expected_difficulty_range": [1, 2],
        "keywords": ["share", "apples", "equally", "divide", "friends"],
        "target_remediation_titles": [
            "Apple Sharing",
            "Marble Sharing",
            "Seating at the Diner",
            "Packing Tennis Balls",
        ],
    },
    {
        "case_id": 6,
        "skill_id": "3.OA.A.2",
        "misconception": "remainder_rounding_up: student did not know how to handle or interpret equal groups from items",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["marbles", "bags", "equally", "partition", "divide"],
        "target_remediation_titles": [
            "Marble Sharing",
            "Apple Sharing",
            "Seating at the Diner",
            "Ribbon Bows",
        ],
    },
    {
        "case_id": 7,
        "skill_id": "3.OA.A.2",
        "misconception": "measurement_quotitive_confusion: confused number of groups with size of each group in measurement division",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["tennis", "balls", "pack", "cans", "ribbon", "inches"],
        "target_remediation_titles": [
            "Packing Tennis Balls",
            "Ribbon Bows",
            "School Bus Seating",
            "Art Class Supplies",
        ],
    },
    {
        "case_id": 8,
        "skill_id": "3.OA.A.2",
        "misconception": "large_batch_partitioning: difficulty dividing multi-digit quantities across equal containers",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["paintbrushes", "pencils", "warehouse", "distribution", "pallets"],
        "target_remediation_titles": [
            "Art Class Supplies",
            "Pencil Factory Boxing",
            "Warehouse Pallet Distribution",
            "Festival Ticket Distribution",
        ],
    },

    # ── 3. CCSS 3.OA.D.8: Two-Step Word Problems ─────────────────────────────
    {
        "case_id": 9,
        "skill_id": "3.OA.D.8",
        "misconception": "premature_termination_two_step: stopped after first operation in two-step word problem",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["tickets", "ride", "carnival", "remaining", "steps"],
        "target_remediation_titles": [
            "Carnival Ride Tickets",
            "Baking Cookies",
            "Lemonade Stand",
            "Movie Snack Bar",
        ],
    },
    {
        "case_id": 10,
        "skill_id": "3.OA.D.8",
        "misconception": "operation_order_inversion: subtracted before calculating intermediate total cost in change problem",
        "mastery_prob": 0.45,
        "expected_difficulty_range": [2, 3],
        "keywords": ["popcorn", "drink", "snack", "change", "movie", "costs"],
        "target_remediation_titles": [
            "Movie Snack Bar",
            "Lemonade Stand",
            "Baking Cookies",
            "Farmer's Market Apples",
        ],
    },
    {
        "case_id": 11,
        "skill_id": "3.OA.D.8",
        "misconception": "intermediate_subtotal_drop: failed to carry forward remaining harvested amount before grouping into bags",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["apples", "farmer", "harvested", "bags", "remaining", "sold"],
        "target_remediation_titles": [
            "Farmer's Market Apples",
            "Book Sale Savings",
            "Movie Snack Bar",
            "Baking Cookies",
        ],
    },
    {
        "case_id": 12,
        "skill_id": "3.OA.D.8",
        "misconception": "multi_step_budget_constraints: confused multiple unit rates and fixed revenues in large inventory problem",
        "mastery_prob": 0.80,
        "expected_difficulty_range": [3, 5],
        "keywords": ["fundraiser", "t-shirts", "charity", "boxes", "revenue", "auditorium"],
        "target_remediation_titles": [
            "School Fundraiser T-Shirts",
            "Charity 5K Race Registration Budget",
            "Baking Championship Batches",
            "School Auditorium Concert Revenue",
        ],
    },

    # ── 4. CCSS 4.NF.A.1: Equivalent Fractions ───────────────────────────────
    {
        "case_id": 13,
        "skill_id": "4.NF.A.1",
        "misconception": "fraction_inversion: student flipped numerator and denominator when generating equivalent fraction",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["equivalent", "fraction", "numerator", "denominator", "puzzle"],
        "target_remediation_titles": [
            "Equivalent Fractions Puzzle",
            "Equivalent Fractions: Halves to Eighths",
            "Equivalent Fractions: Thirds to Ninths",
            "Fraction Strips: Thirds and Sixths",
        ],
    },
    {
        "case_id": 14,
        "skill_id": "4.NF.A.1",
        "misconception": "additive_equivalence_bias: added the same number to numerator and denominator instead of multiplying by common factor",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["missing", "numerator", "halves", "eighths", "equivalent"],
        "target_remediation_titles": [
            "Equivalent Fractions: Halves to Eighths",
            "Equivalent Fractions: Thirds to Ninths",
            "Equivalent Fractions: Fourths to Twelfths",
            "Equivalent Fractions Puzzle",
        ],
    },
    {
        "case_id": 15,
        "skill_id": "4.NF.A.1",
        "misconception": "incomplete_simplification: divided by a common factor but stopped before reaching lowest terms",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["simplify", "simplest", "lowest", "terms", "dividing"],
        "target_remediation_titles": [
            "Simplifying Six-Tenths",
            "Simplifying Tenths: Four-Tenths",
            "Simplifying Fifteenths: Nine-Fifteenths",
            "Simplifying 18/24",
            "Simplifying Thirty-Sixths: 24/36",
        ],
    },
    {
        "case_id": 16,
        "skill_id": "4.NF.A.1",
        "misconception": "cross_multiplication_misalignment: struggled to balance multi-step equivalence equations with missing variable denominators",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["chain", "unknowns", "equivalence", "compare", "ruler", "scaling"],
        "target_remediation_titles": [
            "Comparing Fractions on a Ruler: 5/8 vs 7/12",
            "Architect Blueprint Scaling",
            "Three-Way Fraction Equivalence",
            "Fraction Equivalence with Unknowns",
            "Chain of Equivalent Fractions Puzzle",
        ],
    },

    # ── 5. CCSS 4.NF.B.3: Adding & Subtracting Fractions ─────────────────────
    {
        "case_id": 17,
        "skill_id": "4.NF.B.3",
        "misconception": "denominator_addition: student added bottom denominators directly 1/3 + 1/4 = 2/7",
        "mastery_prob": 0.25,
        "expected_difficulty_range": [1, 2],
        "keywords": ["denominator", "fraction", "add", "pizza", "slices"],
        "target_remediation_titles": [
            "Pizza Fractions",
            "Pie Slices Addition",
            "Juice Pitcher Subtraction",
            "Walking Trails: Unlike Denominators",
        ],
    },
    {
        "case_id": 18,
        "skill_id": "4.NF.B.3",
        "misconception": "unlike_denominator_blind_subtraction: subtracted numerators while ignoring mismatched denominators",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["subtraction", "pitcher", "ribbon", "cutting", "fraction"],
        "target_remediation_titles": [
            "Juice Pitcher Subtraction",
            "Ribbon Cutting",
            "Lumber Plank Cutting",
            "Pizza Fractions",
        ],
    },
    {
        "case_id": 19,
        "skill_id": "4.NF.B.3",
        "misconception": "common_denominator_scaling_error: failed to multiply numerator when converting to common denominator",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["unlike", "denominators", "trails", "flour", "thirds", "fifths"],
        "target_remediation_titles": [
            "Walking Trails: Unlike Denominators",
            "Flour Jar Addition: Fifths and Thirds",
            "Running Distance",
            "Ribbon Cutting",
        ],
    },
    {
        "case_id": 20,
        "skill_id": "4.NF.B.3",
        "misconception": "mixed_number_regrouping_error: subtracted whole numbers and fractional parts without borrowing from whole",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["mixed", "regrouping", "subtracting", "milk", "triathalon"],
        "target_remediation_titles": [
            "Mixed Number Milk Usage",
            "Subtracting with Regrouping",
            "Three Fraction Triathalon",
            "Flour Jar Addition: Fifths and Thirds",
        ],
    },

    # ── 6. CCSS 4.NF.B.4: Multiplying Fractions by Whole Numbers ─────────────
    {
        "case_id": 21,
        "skill_id": "4.NF.B.4",
        "misconception": "both_parts_multiplication: multiplied whole number with both numerator and denominator e.g. 3 * (2/5) = 6/15",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["sprinkles", "cupcake", "repeated", "fraction", "multiply"],
        "target_remediation_titles": [
            "Repeated Fraction: Cupcake Sprinkles",
            "Dog Food Portions",
            "Fraction of a Group",
            "Fraction Multiplication",
        ],
    },
    {
        "case_id": 22,
        "skill_id": "4.NF.B.4",
        "misconception": "fraction_of_whole_inversion: inverted fraction when finding fraction of a whole collection",
        "mastery_prob": 0.40,
        "expected_difficulty_range": [1, 2],
        "keywords": ["portions", "meals", "dog", "food", "fraction", "multiply"],
        "target_remediation_titles": [
            "Dog Food Portions",
            "Repeated Fraction: Cupcake Sprinkles",
            "Fraction Multiplication",
            "Ribbon for Gift Packages",
        ],
    },
    {
        "case_id": 23,
        "skill_id": "4.NF.B.4",
        "misconception": "scaling_whole_collection_confusion: divided by numerator instead of denominator when calculating fraction of a group",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["classroom", "fraction", "whole", "students", "ribbon", "packages"],
        "target_remediation_titles": [
            "Classroom Fraction of a Whole",
            "Ribbon for Gift Packages",
            "Running Laps Around the Track",
            "Fuel Tank Capacity",
        ],
    },
    {
        "case_id": 24,
        "skill_id": "4.NF.B.4",
        "misconception": "mixed_number_multiplication_distribution: multiplied whole by whole and fraction by fraction without converting mixed number",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["batch", "recipe", "soup", "kitchen", "multi-step", "adjustment"],
        "target_remediation_titles": [
            "Soup Kitchen Multi-Batch Cooking",
            "Multi-Step Recipe Batch Adjustment",
            "Community Garden Soil Allocation",
            "Aquarium Water Replacement System",
        ],
    },

    # ── 7. CCSS 5.NF.B.7: Dividing Fractions & Unit Fractions ────────────────
    {
        "case_id": 25,
        "skill_id": "5.NF.B.7",
        "misconception": "division_makes_smaller_fallacy: thought dividing whole number by fraction must yield smaller quantity",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["sharing", "unit", "fraction", "brownies", "divide", "siblings"],
        "target_remediation_titles": [
            "Sharing a Unit Fraction",
            "Granola Bar Sharing",
            "Dividing Pizza Equally",
            "Dividing Rope Lengths",
        ],
    },
    {
        "case_id": 26,
        "skill_id": "5.NF.B.7",
        "misconception": "unit_fraction_division_by_whole: multiplied instead of dividing when sharing a unit fraction among friends",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["granola", "bars", "divide", "sharing", "friends", "unit"],
        "target_remediation_titles": [
            "Granola Bar Sharing",
            "Sharing a Unit Fraction",
            "Dividing Rope Lengths",
            "Dividing Pizza Equally",
        ],
    },
    {
        "case_id": 27,
        "skill_id": "5.NF.B.7",
        "misconception": "measurement_division_reciprocal_neglect: failed to multiply by reciprocal when finding number of fractional scoops in whole container",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["scoops", "flour", "measuring", "pancake", "batter", "reciprocal"],
        "target_remediation_titles": [
            "Measuring Scoops of Flour",
            "Pancake Batter Portions",
            "Dividing Whole Number by Non-Unit Fraction",
            "Flower Garden",
        ],
    },
    {
        "case_id": 28,
        "skill_id": "5.NF.B.7",
        "misconception": "mixed_number_fraction_division_inversion: inverted dividend instead of divisor in multi-step measurement division",
        "mastery_prob": 0.80,
        "expected_difficulty_range": [3, 5],
        "keywords": ["trail", "marker", "intervals", "bottling", "industrial", "shelving"],
        "target_remediation_titles": [
            "Dividing Fraction by Fraction",
            "Hiking Trail Marker Intervals",
            "Industrial Fluid Bottling Line",
            "Carpenter's Precision Shelving",
        ],
    },

    # ── 8. CCSS 6.EE.A.2: Writing & Evaluating Algebraic Expressions ─────────
    {
        "case_id": 29,
        "skill_id": "6.EE.A.2",
        "misconception": "order_of_operations_skip: evaluated 2 + 3 * 4 as 20 instead of 14, ignoring operator precedence",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["translating", "sums", "algebra", "expression", "variable"],
        "target_remediation_titles": [
            "Translating Sums into Algebra",
            "Translating Differences into Algebra",
            "Algebra: Bag of Marbles",
            "Writing Product Expressions",
        ],
    },
    {
        "case_id": 30,
        "skill_id": "6.EE.A.2",
        "misconception": "subtraction_order_reversal: translated '7 less than x' as 7 - x instead of x - 7",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["translating", "differences", "algebra", "less", "subtraction"],
        "target_remediation_titles": [
            "Translating Differences into Algebra",
            "Translating Sums into Algebra",
            "Writing Quotient Expressions",
            "Algebra: Bag of Marbles",
        ],
    },
    {
        "case_id": 31,
        "skill_id": "6.EE.A.2",
        "misconception": "distributive_parentheses_omission: translated '5 times the sum of x and 3' as 5x + 3 omitting parentheses",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["products", "sums", "translating", "ticket", "prices", "expression"],
        "target_remediation_titles": [
            "Translating Products and Sums",
            "Two-Part Expression: Ticket Prices",
            "Expressions with Two Variables",
            "Evaluating an Expression",
        ],
    },
    {
        "case_id": 32,
        "skill_id": "6.EE.A.2",
        "misconception": "exponent_precedence_in_evaluation: multiplied base by coefficient before squaring in multi-variable expression",
        "mastery_prob": 0.75,
        "expected_difficulty_range": [3, 5],
        "keywords": ["evaluating", "expression", "multi-variable", "rational", "perimeter", "cylinder"],
        "target_remediation_titles": [
            "Evaluating an Expression",
            "Evaluating Multi-Variable Rational Expression",
            "Multi-Variable Store Inventory",
            "Phone Plan Monthly Bill Expression",
        ],
    },

    # ── 9. CCSS 6.EE.B.7: One-Step Linear Equations ──────────────────────────
    {
        "case_id": 33,
        "skill_id": "6.EE.B.7",
        "misconception": "variable_coefficient_ignored: student solved 3x = 12 as x = 12 by dropping coefficient",
        "mastery_prob": 0.25,
        "expected_difficulty_range": [1, 2],
        "keywords": ["solve", "division", "equation", "multiplication", "isolate"],
        "target_remediation_titles": [
            "Solve for x: Division",
            "Solving Multiplication Equation",
            "One-Step Multiplication: 10m = 240",
            "Solve for x: Simple",
        ],
    },
    {
        "case_id": 34,
        "skill_id": "6.EE.B.7",
        "misconception": "inverse_operation_confusion: subtracted instead of adding when isolating variable with negative constant x - 8 = 21",
        "mastery_prob": 0.30,
        "expected_difficulty_range": [1, 2],
        "keywords": ["subtraction", "addition", "solve", "equation", "isolate"],
        "target_remediation_titles": [
            "Solving Subtraction Equation",
            "Solving Addition Equation",
            "One-Step Subtraction with Multi-Digit Numbers",
            "Solve for x: Simple",
        ],
    },
    {
        "case_id": 35,
        "skill_id": "6.EE.B.7",
        "misconception": "fractional_coefficient_multiplication: multiplied by numerator instead of multiplying by reciprocal for (3/4)x = 18",
        "mastery_prob": 0.55,
        "expected_difficulty_range": [2, 3],
        "keywords": ["fraction", "coefficient", "half", "number", "solve", "equation"],
        "target_remediation_titles": [
            "Fraction Coefficient: Half of a Number",
            "One-Step Equation with Fractions",
            "Solving Division Equation",
            "One-Step Decimals: Savings Account",
        ],
    },
    {
        "case_id": 36,
        "skill_id": "6.EE.B.7",
        "misconception": "negative_coefficient_sign_error: dropped negative sign when dividing both sides by negative rational coefficient",
        "mastery_prob": 0.80,
        "expected_difficulty_range": [3, 5],
        "keywords": ["rational", "coefficient", "negative", "fraction", "submarine", "speed"],
        "target_remediation_titles": [
            "Rational Coefficient Equation",
            "One-Step Equation with Negative Fraction",
            "Geometry Equilateral Triangle Perimeter",
            "Submarine Depth Change Equation",
        ],
    },

    # ── 10. CCSS 7.EE.B.4: Two-Step Linear Equations & Inequalities ──────────
    {
        "case_id": 37,
        "skill_id": "7.EE.B.4",
        "misconception": "two_step_constant_first_neglect: divided by coefficient before subtracting constant term in 2x + 3 = 11",
        "mastery_prob": 0.35,
        "expected_difficulty_range": [1, 2],
        "keywords": ["two-step", "linear", "equation", "solve", "subtraction"],
        "target_remediation_titles": [
            "Two-Step Linear Equation",
            "Two-Step Equation",
            "Two-Step with Subtraction",
            "Distributive Property Equation",
        ],
    },
    {
        "case_id": 38,
        "skill_id": "7.EE.B.4",
        "misconception": "distributive_expansion_sign_error: neglected to distribute negative across second term in -2(x + 5) = 14",
        "mastery_prob": 0.50,
        "expected_difficulty_range": [2, 3],
        "keywords": ["distributive", "negatives", "equation", "parentheses", "property"],
        "target_remediation_titles": [
            "Distributive Property with Negatives",
            "Distributive Property Equation",
            "Two-Step with Negative Variable Term",
            "Variables on Both Sides",
        ],
    },
    {
        "case_id": 39,
        "skill_id": "7.EE.B.4",
        "misconception": "sign_flip_division_negative: forgot to flip inequality symbol when dividing both sides by negative number",
        "mastery_prob": 0.70,
        "expected_difficulty_range": [3, 5],
        "keywords": ["negative", "coefficient", "inequality", "sign", "flip", "linear"],
        "target_remediation_titles": [
            "Negative Coefficient Inequality with Sign Flip",
            "Negative Distributive Inequality",
            "Solving Multi-Step Linear Inequality",
            "Challenge: Inequality",
        ],
    },
    {
        "case_id": 40,
        "skill_id": "7.EE.B.4",
        "misconception": "inequality_boundary_direction_inversion: inverted strict inequality constraint when translating word problem budget",
        "mastery_prob": 0.80,
        "expected_difficulty_range": [3, 5],
        "keywords": ["taxi", "fare", "budget", "inequality", "business", "profit"],
        "target_remediation_titles": [
            "Taxi Fare Budget Inequality",
            "Comprehensive Business Profit Inequality",
            "Solving Linear Inequality: 4x + 9 > 33",
            "Challenge: Inequality",
        ],
    },
]


def run_retrieval_benchmark(mode: str = "pgvector", verbose: bool = False) -> dict:
    mode_name = "PGVECTOR DENSE RETRIEVAL (768-DIM)" if mode == "pgvector" else "LEXICAL FALLBACK RETRIEVAL (BM25/TOKEN)"
    print("\n" + "=" * 80)
    print(f"   VERITAS RAG RETRIEVAL BENCHMARK: {mode_name}")
    print("=" * 80)
    print("Pipeline: Diagnosed Misconception -> Unrestricted Pool Search (208 problems)")
    print(f"          -> Adaptive Pedagogical Ranker [mode={mode}] -> Human-Labelled Targets")
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
            mode=mode,
        )

        if not candidates:
            print(f" [Query #{i:02d}] {target_skill:<9} | FAILED (No candidates returned)")
            continue

        # Evaluate candidate ranking against human-labelled ground truth
        first_remediation_rank = None
        for rank_idx, cand in enumerate(candidates, start=1):
            cand_title = cand.get("title", "")
            is_target_remediation = any(t.lower() in cand_title.lower() for t in target_titles)
            if is_target_remediation and first_remediation_rank is None:
                first_remediation_rank = rank_idx

        # Calculate Reciprocal Rank and Recall@K
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

        if verbose:
            print(f"\n[Case {i:02d}] Diagnosed Error: \"{misc[:55]}...\"")
            print(f"          Target Skill: {target_skill} | Target ZPD: Diff {exp_range[0]}-{exp_range[1]} | Student Mastery: {mastery:.2f}")
            print(f"          Keywords: {', '.join(kws)}")
            for r_idx, c in enumerate(candidates, start=1):
                c_skill = c.get("skill_id")
                c_diff = c.get("difficulty", 1)
                c_title = c.get("title", "")
                is_remed = any(t.lower() in c_title.lower() for t in target_titles)
                is_sk = (c_skill == target_skill)
                tags = []
                if is_remed:
                    tags.append("REMEDIATION TARGET")
                if is_sk:
                    tags.append(f"Skill {c_skill}")
                tag_str = f" <-- [{', '.join(tags)}]" if tags else ""
                print(f"          * Rank {r_idx}: \"{c_title[:32]}\" ({c_skill}, diff {c_diff}/5){tag_str}")
            rr_val = (1.0 / first_remediation_rank) if first_remediation_rank else 0.0
            print(f"          => First Remediation Rank: {first_remediation_rank or 'Not found in Top 5'} | RR: {rr_val:.4f}")
        else:
            rank_display = f"Rank #{first_remediation_rank}" if first_remediation_rank else "Miss (>5)"
            top_title = top_cand.get('title', '')[:28]
            sk_ok = "PASS" if top_skill == target_skill else "FAIL"
            print(f" [{i:02d}/{n_cases}] {target_skill:<9} | Top-1: \"{top_title:<28}\" | Remediation: {rank_display:<10} | Skill: {sk_ok}")

    r1 = (recall_at_1 / n_cases) * 100.0
    r3 = (recall_at_3 / n_cases) * 100.0
    r5 = (recall_at_5 / n_cases) * 100.0
    mrr = mrr_sum / n_cases
    skill_accuracy = (skill_match_count / n_cases) * 100.0
    diff_accuracy = (diff_match_count / n_cases) * 100.0
    kw_match_rate = (total_keyword_matches / total_keywords_tested) * 100.0 if total_keywords_tested > 0 else 0.0

    print("\n" + "=" * 80)
    print(f"VERITAS RAG RETRIEVAL SUMMARY: {mode.upper()} MODE (n={n_cases})")
    print("=" * 80)
    print(f" • Total Diagnostic Test Queries  : {n_cases} (n={n_cases})")
    print(f" • Candidate Pool Scope           : Unrestricted (all 208 problems across 10 skills)")
    print(f" • Top-1 Skill Precision         : {skill_accuracy:.1f}% ({skill_match_count}/{n_cases}) [n={n_cases}]")
    print(f" • Top-1 Difficulty (ZPD) Fit     : {diff_accuracy:.1f}% ({diff_match_count}/{n_cases}) [n={n_cases}]")
    print(f" • Misconception Keyword Coverage : {kw_match_rate:.1f}% ({total_keyword_matches}/{total_keywords_tested}) [n={total_keywords_tested}]")
    print(f" • Recall@1 (Remediation at #1)   : {r1:.1f}% ({recall_at_1}/{n_cases}) [n={n_cases}]")
    print(f" • Recall@3 (Remediation in Top 3): {r3:.1f}% ({recall_at_3}/{n_cases}) [n={n_cases}]")
    print(f" • Recall@5 (Remediation in Top 5): {r5:.1f}% ({recall_at_5}/{n_cases}) [n={n_cases}]")
    print(f" • Mean Reciprocal Rank (MRR)     : {mrr:.4f} [n={n_cases}]")
    print("=" * 80 + "\n")

    return {
        "mode": mode,
        "total_queries": n_cases,
        "n": n_cases,
        "skill_match_count": skill_match_count,
        "skill_match_rate": round(skill_accuracy, 2),
        "difficulty_fit_count": diff_match_count,
        "difficulty_fit_rate": round(diff_accuracy, 2),
        "total_keyword_matches": total_keyword_matches,
        "total_keywords_tested": total_keywords_tested,
        "keyword_match_rate": round(kw_match_rate, 2),
        "recall_at_1": round(r1, 2),
        "recall_at_3": round(r3, 2),
        "recall_at_5": round(r5, 2),
        "mrr": round(mrr, 4),
        "passed": (r3 >= 80.0 and mrr >= 0.70 and skill_accuracy >= 80.0),
    }


def print_comparison_table(pg_res: dict, lex_res: dict):
    n = pg_res["n"]
    width = 86
    print("=" * width)
    print("VERITAS RETRIEVAL BENCHMARK: PGVECTOR VS LEXICAL-FALLBACK COMPARISON".center(width))
    print("=" * width)
    print(f" {'METRIC DIMENSION':<34} | {'TARGET':<10} | {'PGVECTOR (n=' + str(n) + ')':<18} | {'LEXICAL (n=' + str(n) + ')':<16}")
    print("-" * width)
    print(f" {'Top-1 Skill Precision':<34} | {'> 80.0%':<10} | {pg_res['skill_match_rate']:.1f}% [n={n}]        | {lex_res['skill_match_rate']:.1f}% [n={n}]")
    print(f" {'Top-1 Difficulty (ZPD) Fit':<34} | {'> 75.0%':<10} | {pg_res['difficulty_fit_rate']:.1f}% [n={n}]        | {lex_res['difficulty_fit_rate']:.1f}% [n={n}]")
    print(f" {'Misconception Keyword Coverage':<34} | {'> 50.0%':<10} | {pg_res['keyword_match_rate']:.1f}% [n={pg_res['total_keywords_tested']}]      | {lex_res['keyword_match_rate']:.1f}% [n={lex_res['total_keywords_tested']}]")
    print(f" {'Recall@1 (Target Problem at #1)':<34} | {'> 60.0%':<10} | {pg_res['recall_at_1']:.1f}% [n={n}]        | {lex_res['recall_at_1']:.1f}% [n={n}]")
    print(f" {'Recall@3 (Target in Top 3)':<34} | {'> 80.0%':<10} | {pg_res['recall_at_3']:.1f}% [n={n}]        | {lex_res['recall_at_3']:.1f}% [n={n}]")
    print(f" {'Recall@5 (Target in Top 5)':<34} | {'> 90.0%':<10} | {pg_res['recall_at_5']:.1f}% [n={n}]        | {lex_res['recall_at_5']:.1f}% [n={n}]")
    print(f" {'Mean Reciprocal Rank (MRR)':<34} | {'> 0.7000':<10} | {pg_res['mrr']:.4f} [n={n}]       | {lex_res['mrr']:.4f} [n={n}]")
    print("=" * width + "\n")


def main():
    parser = argparse.ArgumentParser(description="Veritas RAG Retrieval Benchmark")
    parser.add_argument("--mode", choices=["both", "pgvector", "lexical"], default="both", help="Evaluation mode")
    parser.add_argument("--verbose", action="store_true", help="Print verbose candidate ranking per query")
    args = parser.parse_args()

    if args.mode == "both":
        pg_results = run_retrieval_benchmark(mode="pgvector", verbose=args.verbose)
        lex_results = run_retrieval_benchmark(mode="lexical", verbose=args.verbose)
        print_comparison_table(pg_results, lex_results)
        sys.exit(0 if (pg_results["passed"] and lex_results["passed"]) else 1)
    else:
        results = run_retrieval_benchmark(mode=args.mode, verbose=args.verbose)
        sys.exit(0 if results["passed"] else 1)


if __name__ == "__main__":
    main()
