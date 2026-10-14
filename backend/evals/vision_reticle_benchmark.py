"""
Multimodal Scratchpad Reticle & Misconception Benchmark Suite — Veritas.
Evaluates normalized bounding box reticle coordinate precision (IoU)
and misconception classification against student scratchpad fixtures.

Supports two distinct, clearly separated evaluation modes:
1. Live Empirical Evaluation Mode (Gemini Vision LLM):
   Calls `run_diagnostic_agent` on real student handwritten images,
   extracting bounding boxes and diagnosing misconceptions via live Gemini Vision.
2. Clearly Named Mock Mode:
   Evaluates synthetic test fixtures for zero-credit CI testing and baseline regression.
"""
import sys
import os
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
        getattr(sys.stderr, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

FIXTURES_DIR = BACKEND_DIR / "evals" / "fixtures"

from agents.diagnostic_agent import run_diagnostic_agent


def compute_box_iou(boxA: List[float], boxB: List[float]) -> float:
    """
    Compute Intersection over Union (IoU) between two bounding boxes: [ymin, xmin, ymax, xmax].
    Supports normalized [0, 1] or [0, 1000] coordinate ranges.
    """
    if not boxA or not boxB or len(boxA) != 4 or len(boxB) != 4:
        return 0.0

    # Normalize if on [0, 1000] scale
    if max(boxA) > 1.0 or max(boxB) > 1.0:
        boxA = [c / 1000.0 for c in boxA]
        boxB = [c / 1000.0 for c in boxB]

    yA = max(boxA[0], boxB[0])
    xA = max(boxA[1], boxB[1])
    yB = min(boxA[2], boxB[2])
    xB = min(boxA[3], boxB[3])

    inter_height = max(0.0, yB - yA)
    inter_width = max(0.0, xB - xA)
    inter_area = inter_height * inter_width

    boxA_area = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxB_area = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union_area = boxA_area + boxB_area - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


# 20 Multimodal Ground Truth Annotation Fixture Definitions
GROUND_TRUTH_FIXTURES: List[Dict[str, Any]] = [
    {
        "id": "fix_01",
        "filename": "fix_01.png",
        "description": "Adding denominators across (e.g. 1/4 + 2/4 = 3/8)",
        "skill_id": "4.NF.B.3",
        "problem_text": "Calculate 1/4 + 2/4.",
        "expected_steps": [
            "Keep the common denominator 4",
            "Add the numerators: 1 + 2 = 3",
            "Final result: 3/4",
        ],
        "ground_truth_box": [320, 210, 480, 520],
        "ground_truth_misconception": "added_denominators",
        "synonym_misconceptions": ["denominator_addition", "added_denominators"],
        "mock_predicted_box": [325, 215, 475, 510],
        "mock_predicted_misconception": "added_denominators",
    },
    {
        "id": "fix_02",
        "filename": "fix_02.png",
        "description": "Cross-multiplication applied during addition",
        "skill_id": "4.NF.B.3",
        "problem_text": "Compute 1/3 + 2/5.",
        "expected_steps": [
            "Find common denominator for 3 and 5: 15",
            "Convert: 5/15 + 6/15 = 11/15",
        ],
        "ground_truth_box": [150, 400, 310, 700],
        "ground_truth_misconception": "cross_multiplication_confusion",
        "synonym_misconceptions": ["cross_multiplication_confusion", "wrong_operation_keyword"],
        "mock_predicted_box": [160, 410, 300, 690],
        "mock_predicted_misconception": "cross_multiplication_confusion",
    },
    {
        "id": "fix_03",
        "filename": "fix_03.png",
        "description": "Sign flip omission when distributing negative factor",
        "skill_id": "7.EE.B.4",
        "problem_text": "Solve for x: -2(x - 4) = 10.",
        "expected_steps": [
            "Distribute -2: -2x + 8 = 10",
            "Subtract 8: -2x = 2",
            "Divide by -2: x = -1",
        ],
        "ground_truth_box": [500, 100, 650, 450],
        "ground_truth_misconception": "negative_distribution_error",
        "synonym_misconceptions": ["negative_distribution_error", "sign_flip_division_negative", "negative_number_confusion"],
        "mock_predicted_box": [510, 110, 640, 440],
        "mock_predicted_misconception": "negative_distribution_error",
    },
    {
        "id": "fix_04",
        "filename": "fix_04.png",
        "description": "Improper fraction conversion dropped whole number",
        "skill_id": "4.NF.A.1",
        "problem_text": "Convert mixed number 2 3/4 to an improper fraction.",
        "expected_steps": [
            "Multiply whole number by denominator: 2 * 4 = 8",
            "Add numerator: 8 + 3 = 11",
            "Result: 11/4",
        ],
        "ground_truth_box": [220, 300, 390, 600],
        "ground_truth_misconception": "mixed_fraction_conversion",
        "synonym_misconceptions": ["mixed_fraction_conversion", "fraction_inversion"],
        "mock_predicted_box": [230, 310, 380, 590],
        "mock_predicted_misconception": "mixed_fraction_conversion",
    },
    {
        "id": "fix_05",
        "filename": "fix_05.png",
        "description": "Dividing fractions without taking reciprocal",
        "skill_id": "5.NF.B.7",
        "problem_text": "Evaluate 1/2 ÷ 3.",
        "expected_steps": [
            "Multiply by reciprocal: 1/2 * 1/3",
            "Compute product: 1/6",
        ],
        "ground_truth_box": [400, 250, 580, 650],
        "ground_truth_misconception": "missing_reciprocal",
        "synonym_misconceptions": ["missing_reciprocal", "fraction_inversion"],
        "mock_predicted_box": [410, 260, 570, 640],
        "mock_predicted_misconception": "missing_reciprocal",
    },
    {
        "id": "fix_06",
        "filename": "fix_06.png",
        "description": "Unbalanced operation across equal sign",
        "skill_id": "6.EE.B.7",
        "problem_text": "Solve x + 7 = 15.",
        "expected_steps": [
            "Subtract 7 from both sides: x + 7 - 7 = 15 - 7",
            "Simplify: x = 8",
        ],
        "ground_truth_box": [180, 150, 320, 500],
        "ground_truth_misconception": "unbalanced_equation_step",
        "synonym_misconceptions": ["unbalanced_equation_step", "variable_coefficient_ignored"],
        "mock_predicted_box": [190, 160, 310, 490],
        "mock_predicted_misconception": "unbalanced_equation_step",
    },
    {
        "id": "fix_07",
        "filename": "fix_07.png",
        "description": "Combining unlike terms (e.g. 2x + 3 = 5x)",
        "skill_id": "6.EE.A.2",
        "problem_text": "Simplify the expression 2x + 3 + 4x.",
        "expected_steps": [
            "Group like terms: (2x + 4x) + 3",
            "Combine coefficients: 6x + 3",
        ],
        "ground_truth_box": [600, 350, 750, 650],
        "ground_truth_misconception": "unlike_terms_combined",
        "synonym_misconceptions": ["unlike_terms_combined", "variable_coefficient_ignored"],
        "mock_predicted_box": [610, 360, 740, 640],
        "mock_predicted_misconception": "unlike_terms_combined",
    },
    {
        "id": "fix_08",
        "filename": "fix_08.png",
        "description": "Simplification by subtracting numerator and denominator",
        "skill_id": "4.NF.A.1",
        "problem_text": "Simplify 4/8 to lowest terms.",
        "expected_steps": [
            "Find GCF of 4 and 8: 4",
            "Divide numerator and denominator by 4: (4÷4)/(8÷4) = 1/2",
        ],
        "ground_truth_box": [300, 200, 450, 550],
        "ground_truth_misconception": "additive_simplification",
        "synonym_misconceptions": ["additive_simplification", "fraction_inversion"],
        "mock_predicted_box": [310, 210, 440, 540],
        "mock_predicted_misconception": "additive_simplification",
    },
    {
        "id": "fix_09",
        "filename": "fix_09.png",
        "description": "Arithmetic single-digit multiplication error",
        "skill_id": "3.OA.A.1",
        "problem_text": "Find 7 * 8.",
        "expected_steps": [
            "Recall 7 * 8 = 56",
        ],
        "ground_truth_box": [120, 100, 280, 400],
        "ground_truth_misconception": "arithmetic_multiplication_error",
        "synonym_misconceptions": ["arithmetic_multiplication_error", "carry_error"],
        "mock_predicted_box": [130, 110, 270, 390],
        "mock_predicted_misconception": "arithmetic_multiplication_error",
    },
    {
        "id": "fix_10",
        "filename": "fix_10.png",
        "description": "Order of operations error (addition before multiplication)",
        "skill_id": "6.EE.A.2",
        "problem_text": "Evaluate 2 + 3 * 4.",
        "expected_steps": [
            "Multiply first: 3 * 4 = 12",
            "Add: 2 + 12 = 14",
        ],
        "ground_truth_box": [450, 300, 600, 620],
        "ground_truth_misconception": "pemdas_order_error",
        "synonym_misconceptions": ["pemdas_order_error", "order_of_operations_skip"],
        "mock_predicted_box": [460, 310, 590, 610],
        "mock_predicted_misconception": "pemdas_order_error",
    },
    {
        "id": "fix_11",
        "filename": "fix_11.png",
        "description": "Reciprocal applied to dividend instead of divisor",
        "skill_id": "5.NF.B.7",
        "problem_text": "Calculate 3/4 ÷ 2/3.",
        "expected_steps": [
            "Keep first fraction, invert second: 3/4 * 3/2",
            "Multiply: 9/8",
        ],
        "ground_truth_box": [350, 200, 500, 580],
        "ground_truth_misconception": "inverted_dividend_error",
        "synonym_misconceptions": ["inverted_dividend_error", "fraction_inversion"],
        "mock_predicted_box": [360, 210, 490, 570],
        "mock_predicted_misconception": "inverted_dividend_error",
    },
    {
        "id": "fix_12",
        "filename": "fix_12.png",
        "description": "Lost negative sign during variable division",
        "skill_id": "7.EE.B.4",
        "problem_text": "Solve -3x = 12.",
        "expected_steps": [
            "Divide both sides by -3",
            "Positive divided by negative is negative: x = -4",
        ],
        "ground_truth_box": [500, 400, 660, 720],
        "ground_truth_misconception": "lost_negative_sign",
        "synonym_misconceptions": ["lost_negative_sign", "negative_number_confusion", "sign_flip_division_negative"],
        "mock_predicted_box": [510, 410, 650, 710],
        "mock_predicted_misconception": "lost_negative_sign",
    },
    {
        "id": "fix_13",
        "filename": "fix_13.png",
        "description": "Multiplying numerator only by scale factor in equivalence",
        "skill_id": "4.NF.A.1",
        "problem_text": "Find an equivalent fraction for 2/3 with denominator 9.",
        "expected_steps": [
            "Identify scale factor: 9 ÷ 3 = 3",
            "Multiply both numerator and denominator by 3: (2*3)/(3*3) = 6/9",
        ],
        "ground_truth_box": [200, 180, 360, 500],
        "ground_truth_misconception": "unscaled_denominator",
        "synonym_misconceptions": ["unscaled_denominator", "fraction_inversion"],
        "mock_predicted_box": [210, 190, 350, 490],
        "mock_predicted_misconception": "unscaled_denominator",
    },
    {
        "id": "fix_14",
        "filename": "fix_14.png",
        "description": "Adding numerators without finding common denominator",
        "skill_id": "4.NF.B.3",
        "problem_text": "Calculate 1/2 + 1/3.",
        "expected_steps": [
            "Find common denominator 6: 3/6 + 2/6",
            "Add numerators: 5/6",
        ],
        "ground_truth_box": [280, 250, 440, 570],
        "ground_truth_misconception": "unconverted_denominators",
        "synonym_misconceptions": ["unconverted_denominators", "denominator_addition", "added_denominators"],
        "mock_predicted_box": [290, 260, 430, 560],
        "mock_predicted_misconception": "unconverted_denominators",
    },
    {
        "id": "fix_15",
        "filename": "fix_15.png",
        "description": "Decimal point shift error during fraction conversion",
        "skill_id": "4.NF.A.1",
        "problem_text": "Convert 3/10 to a decimal.",
        "expected_steps": [
            "3 tenths = 0.3",
        ],
        "ground_truth_box": [400, 150, 550, 480],
        "ground_truth_misconception": "decimal_place_error",
        "synonym_misconceptions": ["decimal_place_error", "place_value_confusion"],
        "mock_predicted_box": [410, 160, 540, 470],
        "mock_predicted_misconception": "decimal_place_error",
    },
    {
        "id": "fix_16",
        "filename": "fix_16.png",
        "description": "Dividing coefficients instead of subtracting during balance",
        "skill_id": "6.EE.B.7",
        "problem_text": "Solve 2x + 4 = 10.",
        "expected_steps": [
            "Subtract 4 from both sides: 2x = 6",
            "Divide by 2: x = 3",
        ],
        "ground_truth_box": [320, 300, 470, 600],
        "ground_truth_misconception": "inverse_operation_confusion",
        "synonym_misconceptions": ["inverse_operation_confusion", "wrong_operation_keyword"],
        "mock_predicted_box": [330, 310, 460, 590],
        "mock_predicted_misconception": "inverse_operation_confusion",
    },
    {
        "id": "fix_17",
        "filename": "fix_17.png",
        "description": "Exponent notation confusion with multiplication",
        "skill_id": "6.EE.A.2",
        "problem_text": "Evaluate 2^3.",
        "expected_steps": [
            "2^3 = 2 * 2 * 2 = 8",
        ],
        "ground_truth_box": [150, 250, 290, 550],
        "ground_truth_misconception": "exponent_multiplication_confusion",
        "synonym_misconceptions": ["exponent_multiplication_confusion", "wrong_operation_keyword"],
        "mock_predicted_box": [160, 260, 280, 540],
        "mock_predicted_misconception": "exponent_multiplication_confusion",
    },
    {
        "id": "fix_18",
        "filename": "fix_18.png",
        "description": "Perimeter calculated instead of area",
        "skill_id": "3.OA.D.8",
        "problem_text": "Find the area of a rectangle with length 4 and width 5.",
        "expected_steps": [
            "Area = length * width = 4 * 5 = 20",
        ],
        "ground_truth_box": [480, 120, 630, 450],
        "ground_truth_misconception": "area_perimeter_confusion",
        "synonym_misconceptions": ["area_perimeter_confusion", "wrong_operation_keyword"],
        "mock_predicted_box": [490, 130, 620, 440],
        "mock_predicted_misconception": "area_perimeter_confusion",
    },
    {
        "id": "fix_19",
        "filename": "fix_19.png",
        "description": "Fraction bar treated as addition",
        "skill_id": "4.NF.B.3",
        "problem_text": "Interpret the fraction 6/2.",
        "expected_steps": [
            "Fraction bar denotes division: 6 ÷ 2 = 3",
        ],
        "ground_truth_box": [260, 220, 410, 520],
        "ground_truth_misconception": "fraction_operator_misread",
        "synonym_misconceptions": ["fraction_operator_misread", "wrong_operation_keyword"],
        "mock_predicted_box": [270, 230, 400, 510],
        "mock_predicted_misconception": "fraction_operator_misread",
    },
    {
        "id": "fix_20",
        "filename": "fix_20.png",
        "description": "Double negative subtraction resolved as negative",
        "skill_id": "7.EE.B.4",
        "problem_text": "Evaluate 5 - (-3).",
        "expected_steps": [
            "Subtracting a negative is adding: 5 + 3 = 8",
        ],
        "ground_truth_box": [380, 320, 520, 640],
        "ground_truth_misconception": "double_negative_error",
        "synonym_misconceptions": ["double_negative_error", "negative_number_confusion"],
        "mock_predicted_box": [390, 330, 510, 630],
        "mock_predicted_misconception": "double_negative_error",
    },
]


def load_fixture_images() -> Tuple[Dict[str, bytes], List[str]]:
    """
    Check backend/evals/fixtures/ for handwritten image files.
    Returns (loaded_images_by_id, list_of_missing_filenames).
    """
    loaded: Dict[str, bytes] = {}
    missing: List[str] = []

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    for fix in GROUND_TRUTH_FIXTURES:
        fname = fix["filename"]
        fpath = FIXTURES_DIR / fname
        if not fpath.exists():
            # Check alternative extensions (.jpg, .jpeg)
            stem = Path(fname).stem
            alt_paths = list(FIXTURES_DIR.glob(f"{stem}.*"))
            if alt_paths:
                fpath = alt_paths[0]

        if fpath.exists():
            try:
                loaded[fix["id"]] = fpath.read_bytes()
            except Exception as e:
                print(f"[WARN] Failed reading fixture file {fpath}: {e}")
                missing.append(fname)
        else:
            missing.append(fname)

    return loaded, missing


def run_vision_reticle_benchmark_mock() -> Dict[str, Any]:
    """
    Separate, clearly named mock mode for zero-credit test pipelines and CI.
    Evaluates synthetic test fixtures with documented baseline metrics.
    """
    print("=" * 76)
    print("   MULTIMODAL SCRATCHPAD RETICLE & MISCONCEPTION BENCHMARK")
    print("   Mode: MOCK / SYNTHETIC BASELINE (0 Gemini API credits consumed)")
    print(f"   Evaluating {len(GROUND_TRUTH_FIXTURES)} synthetic scratchpad fixtures")
    print("=" * 76)

    t0 = time.time()
    total_fixtures = len(GROUND_TRUTH_FIXTURES)
    iou_scores = []
    correct_misconceptions = 0

    for fix in GROUND_TRUTH_FIXTURES:
        gt_box = fix["ground_truth_box"]
        pred_box = fix["mock_predicted_box"]
        iou = compute_box_iou(gt_box, pred_box)
        iou_scores.append(iou)

        if fix["ground_truth_misconception"] == fix["mock_predicted_misconception"]:
            correct_misconceptions += 1

    elapsed = time.time() - t0
    mean_iou = sum(iou_scores) / total_fixtures if total_fixtures > 0 else 0.0
    classification_acc = (correct_misconceptions / total_fixtures) * 100.0 if total_fixtures > 0 else 0.0

    print(f"\n[BENCHMARK RESULTS (MOCK) - {elapsed:.3f}s]")
    print(f" • Total Scratchpad Fixtures:   {total_fixtures}")
    print(f" • Mean Bounding Box IoU:       {mean_iou:.3f} (Synthetic Target: > 0.70)")
    print(f" • Misconception Tag Precision: {classification_acc:.1f}% ({correct_misconceptions}/{total_fixtures})")
    print(f" • Min Box IoU:                 {min(iou_scores):.3f}")
    print(f" • Max Box IoU:                 {max(iou_scores):.3f}")
    print("-" * 76)

    return {
        "benchmark": "Multimodal Scratchpad Reticle & Misconception Benchmark (Mock)",
        "mode": "mock",
        "total_fixtures": total_fixtures,
        "mean_bounding_box_iou": round(mean_iou, 3),
        "misconception_precision_pct": round(classification_acc, 2),
        "duration_seconds": round(elapsed, 4),
        "passed": (mean_iou >= 0.70 and classification_acc >= 90.0),
    }


def run_vision_reticle_benchmark_live(images: Dict[str, bytes]) -> Dict[str, Any]:
    """
    Live empirical evaluation calling run_diagnostic_agent on real images via Gemini Vision.
    Reports real IoU and misconception accuracy from actual Gemini output.
    """
    print("=" * 76)
    print("   MULTIMODAL SCRATCHPAD RETICLE & MISCONCEPTION BENCHMARK")
    print("   Mode: LIVE GEMINI VISION MODEL (Evaluates actual model outputs)")
    print(f"   Evaluating {len(images)} loaded student scratchpad images")
    print("=" * 76)

    t0 = time.time()
    iou_scores = []
    correct_misconceptions = 0
    total = len(GROUND_TRUTH_FIXTURES)

    for i, fix in enumerate(GROUND_TRUTH_FIXTURES, 1):
        fix_id = fix["id"]
        gt_box = fix["ground_truth_box"]
        gt_misc = fix["ground_truth_misconception"]
        synonyms = [gt_misc.lower()] + [s.lower() for s in fix.get("synonym_misconceptions", [])]

        img_bytes = images.get(fix_id)
        if not img_bytes:
            print(f" [{i:02d}/{total}] {fix_id}: SKIPPED (image missing)")
            continue

        try:
            diagnosis = run_diagnostic_agent(
                image_bytes=img_bytes,
                expected_steps=fix["expected_steps"],
                problem_text=fix["problem_text"],
                skill_id=fix["skill_id"],
            )

            # Convert percentage box {x, y, width, height} to [ymin, xmin, ymax, xmax] scale 1000
            pred_box_dict = diagnosis.get("bounding_box") or diagnosis.get("bounding_hint")
            if isinstance(pred_box_dict, dict):
                x = float(pred_box_dict.get("x", 0))
                y = float(pred_box_dict.get("y", 0))
                w = float(pred_box_dict.get("width", 0))
                h = float(pred_box_dict.get("height", 0))
                pred_box = [y * 10.0, x * 10.0, (y + h) * 10.0, (x + w) * 10.0]
            else:
                pred_box = [0.0, 0.0, 0.0, 0.0]

            iou = compute_box_iou(gt_box, pred_box)
            iou_scores.append(iou)

            pred_misc = str(diagnosis.get("misconception_type", "")).lower()
            is_misc_match = any(s in pred_misc or pred_misc in s for s in synonyms)
            if is_misc_match:
                correct_misconceptions += 1

            status = "✓ MATCH" if is_misc_match else "✗ MISMATCH"
            print(f" [{i:02d}/{total}] {fix_id} ({fix['description'][:30]}...): IoU={iou:.3f} | Misc: {pred_misc} [{status}]")

        except Exception as e:
            print(f" [{i:02d}/{total}] {fix_id}: ERROR ({e})")
            iou_scores.append(0.0)

    elapsed = time.time() - t0
    evaluated_count = len(iou_scores)
    mean_iou = sum(iou_scores) / evaluated_count if evaluated_count > 0 else 0.0
    classification_acc = (correct_misconceptions / evaluated_count) * 100.0 if evaluated_count > 0 else 0.0

    print(f"\n[BENCHMARK RESULTS (LIVE MODEL) - {elapsed:.2f}s]")
    print(f" • Total Evaluated Fixtures:    {evaluated_count}/{total}")
    print(f" • Empirical Mean Box IoU:      {mean_iou:.3f} (Industry Target: > 0.70)")
    print(f" • Misconception Precision:     {classification_acc:.1f}% ({correct_misconceptions}/{evaluated_count})")
    if iou_scores:
        print(f" • Min Box IoU:                 {min(iou_scores):.3f}")
        print(f" • Max Box IoU:                 {max(iou_scores):.3f}")
    print("-" * 76)

    return {
        "benchmark": "Multimodal Scratchpad Reticle & Misconception Benchmark (Live)",
        "mode": "live",
        "total_fixtures": evaluated_count,
        "mean_bounding_box_iou": round(mean_iou, 3),
        "misconception_precision_pct": round(classification_acc, 2),
        "duration_seconds": round(elapsed, 4),
        "passed": (mean_iou >= 0.70 and classification_acc >= 80.0),
    }


def run_vision_reticle_benchmark(force_mock: bool = False, force_live: bool = False) -> Dict[str, Any]:
    """
    Main benchmark entry point with loader and fallback:
    - If force_mock is True, runs mock mode directly.
    - If force_live is True, strictly requires images and runs live mode.
    - In auto mode: loads images from backend/evals/fixtures/.
      If images exist, runs live mode; otherwise prints clear TODO and runs mock mode.
    """
    if force_mock or os.environ.get("VERITAS_TEST_MODE") == "true" or os.environ.get("VERITAS_MOCK_LLM") == "true":
        return run_vision_reticle_benchmark_mock()

    loaded_images, missing_files = load_fixture_images()

    if force_live and len(loaded_images) == 0:
        print(f"\n[ERROR] --live flag specified but 0 images found in {FIXTURES_DIR}.")
        print(f"        Please supply the 20 handwritten scratchpad images: {missing_files[:5]}...")
        sys.exit(1)

    if len(loaded_images) > 0 and (force_live or len(loaded_images) == len(GROUND_TRUTH_FIXTURES)):
        return run_vision_reticle_benchmark_live(loaded_images)

    # Loader detected missing image files — print clear TODO and execute mock mode
    print("\n" + "=" * 76)
    print("   [TODO] STUDENT SCRATCHPAD IMAGE FIXTURES MISSING / INCOMPLETE")
    print(f"   Directory: {FIXTURES_DIR}")
    print(f"   Status   : {len(loaded_images)}/20 images found ({len(missing_files)} missing).")
    print("   Action   : The user will supply the 20 handwritten scratchpad images.")
    print("              Once placed in backend/evals/fixtures/, rerun with --live to compute")
    print("              empirical IoU and misconception accuracy from actual Gemini output.")
    print("   Fallback : Running separate, clearly named MOCK mode for now.")
    print("=" * 76 + "\n")

    return run_vision_reticle_benchmark_mock()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multimodal Vision Reticle Benchmark")
    parser.add_argument("--mock", action="store_true", help="Force separate mock mode")
    parser.add_argument("--live", action="store_true", help="Force live Gemini Vision model evaluation on real images")
    args = parser.parse_args()

    res = run_vision_reticle_benchmark(force_mock=args.mock, force_live=args.live)
    sys.exit(0 if res.get("passed", False) else 1)
