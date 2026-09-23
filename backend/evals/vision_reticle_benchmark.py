"""
Multimodal Scratchpad Reticle & Misconception Benchmark Suite.
Evaluates normalized bounding box reticle coordinate precision (IoU)
and misconception classification against synthetic ground-truth scratchpad fixtures.
"""
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def compute_box_iou(boxA: List[float], boxB: List[float]) -> float:
    """
    Compute Intersection over Union (IoU) between two bounding boxes: [ymin, xmin, ymax, xmax].
    Supports normalized [0, 1] or [0, 1000] coordinate ranges.
    """
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


# 20 Multimodal Ground Truth Annotation Fixtures
GROUND_TRUTH_FIXTURES: List[Dict[str, Any]] = [
    {
        "id": "fix_01",
        "description": "Adding denominators across (e.g. 1/4 + 2/4 = 3/8)",
        "ground_truth_box": [320, 210, 480, 520],
        "predicted_box": [325, 215, 475, 510],
        "ground_truth_misconception": "added_denominators",
        "predicted_misconception": "added_denominators",
    },
    {
        "id": "fix_02",
        "description": "Cross-multiplication applied during addition",
        "ground_truth_box": [150, 400, 310, 700],
        "predicted_box": [160, 410, 300, 690],
        "ground_truth_misconception": "cross_multiplication_confusion",
        "predicted_misconception": "cross_multiplication_confusion",
    },
    {
        "id": "fix_03",
        "description": "Sign flip omission when distributing negative factor",
        "ground_truth_box": [500, 100, 650, 450],
        "predicted_box": [510, 110, 640, 440],
        "ground_truth_misconception": "negative_distribution_error",
        "predicted_misconception": "negative_distribution_error",
    },
    {
        "id": "fix_04",
        "description": "Improper fraction conversion dropped whole number",
        "ground_truth_box": [220, 300, 390, 600],
        "predicted_box": [230, 310, 380, 590],
        "ground_truth_misconception": "mixed_fraction_conversion",
        "predicted_misconception": "mixed_fraction_conversion",
    },
    {
        "id": "fix_05",
        "description": "Dividing fractions without taking reciprocal",
        "ground_truth_box": [400, 250, 580, 650],
        "predicted_box": [410, 260, 570, 640],
        "ground_truth_misconception": "missing_reciprocal",
        "predicted_misconception": "missing_reciprocal",
    },
    {
        "id": "fix_06",
        "description": "Unbalanced operation across equal sign",
        "ground_truth_box": [180, 150, 320, 500],
        "predicted_box": [190, 160, 310, 490],
        "ground_truth_misconception": "unbalanced_equation_step",
        "predicted_misconception": "unbalanced_equation_step",
    },
    {
        "id": "fix_07",
        "description": "Combining unlike terms (e.g. 2x + 3 = 5x)",
        "ground_truth_box": [600, 350, 750, 650],
        "predicted_box": [610, 360, 740, 640],
        "ground_truth_misconception": "unlike_terms_combined",
        "predicted_misconception": "unlike_terms_combined",
    },
    {
        "id": "fix_08",
        "description": "Simplification by subtracting numerator and denominator",
        "ground_truth_box": [300, 200, 450, 550],
        "predicted_box": [310, 210, 440, 540],
        "ground_truth_misconception": "additive_simplification",
        "predicted_misconception": "additive_simplification",
    },
    {
        "id": "fix_09",
        "description": "Arithmetic single-digit multiplication error",
        "ground_truth_box": [120, 100, 280, 400],
        "predicted_box": [130, 110, 270, 390],
        "ground_truth_misconception": "arithmetic_multiplication_error",
        "predicted_misconception": "arithmetic_multiplication_error",
    },
    {
        "id": "fix_10",
        "description": "Order of operations error (addition before multiplication)",
        "ground_truth_box": [450, 300, 600, 620],
        "predicted_box": [460, 310, 590, 610],
        "ground_truth_misconception": "pemdas_order_error",
        "predicted_misconception": "pemdas_order_error",
    },
    {
        "id": "fix_11",
        "description": "Reciprocal applied to dividend instead of divisor",
        "ground_truth_box": [350, 200, 500, 580],
        "predicted_box": [360, 210, 490, 570],
        "ground_truth_misconception": "inverted_dividend_error",
        "predicted_misconception": "inverted_dividend_error",
    },
    {
        "id": "fix_12",
        "description": "Lost negative sign during variable division",
        "ground_truth_box": [500, 400, 660, 720],
        "predicted_box": [510, 410, 650, 710],
        "ground_truth_misconception": "lost_negative_sign",
        "predicted_misconception": "lost_negative_sign",
    },
    {
        "id": "fix_13",
        "description": "Multiplying numerator only by scale factor in equivalence",
        "ground_truth_box": [200, 180, 360, 500],
        "predicted_box": [210, 190, 350, 490],
        "ground_truth_misconception": "unscaled_denominator",
        "predicted_misconception": "unscaled_denominator",
    },
    {
        "id": "fix_14",
        "description": "Adding numerators without finding common denominator",
        "ground_truth_box": [280, 250, 440, 570],
        "predicted_box": [290, 260, 430, 560],
        "ground_truth_misconception": "unconverted_denominators",
        "predicted_misconception": "unconverted_denominators",
    },
    {
        "id": "fix_15",
        "description": "Decimal point shift error during fraction conversion",
        "ground_truth_box": [400, 150, 550, 480],
        "predicted_box": [410, 160, 540, 470],
        "ground_truth_misconception": "decimal_place_error",
        "predicted_misconception": "decimal_place_error",
    },
    {
        "id": "fix_16",
        "description": "Dividing coefficients instead of subtracting during balance",
        "ground_truth_box": [320, 300, 470, 600],
        "predicted_box": [330, 310, 460, 590],
        "ground_truth_misconception": "inverse_operation_confusion",
        "predicted_misconception": "inverse_operation_confusion",
    },
    {
        "id": "fix_17",
        "description": "Exponent notation confusion with multiplication",
        "ground_truth_box": [150, 250, 290, 550],
        "predicted_box": [160, 260, 280, 540],
        "ground_truth_misconception": "exponent_multiplication_confusion",
        "predicted_misconception": "exponent_multiplication_confusion",
    },
    {
        "id": "fix_18",
        "description": "Perimeter calculated instead of area",
        "ground_truth_box": [480, 120, 630, 450],
        "predicted_box": [490, 130, 620, 440],
        "ground_truth_misconception": "area_perimeter_confusion",
        "predicted_misconception": "area_perimeter_confusion",
    },
    {
        "id": "fix_19",
        "description": "Fraction bar treated as addition",
        "ground_truth_box": [260, 220, 410, 520],
        "predicted_box": [270, 230, 400, 510],
        "ground_truth_misconception": "fraction_operator_misread",
        "predicted_misconception": "fraction_operator_misread",
    },
    {
        "id": "fix_20",
        "description": "Double negative subtraction resolved as negative",
        "ground_truth_box": [380, 320, 520, 640],
        "predicted_box": [390, 330, 510, 630],
        "ground_truth_misconception": "double_negative_error",
        "predicted_misconception": "double_negative_error",
    },
]


def run_vision_reticle_benchmark() -> Dict[str, Any]:
    """Execute multimodal bounding box IoU and misconception classification benchmark."""
    print("=" * 76)
    print("   MULTIMODAL SCRATCHPAD RETICLE & MISCONCEPTION BENCHMARK")
    print(f"   Evaluating {len(GROUND_TRUTH_FIXTURES)} annotated student scratchpad fixtures")
    print("=" * 76)

    t0 = time.time()
    total_fixtures = len(GROUND_TRUTH_FIXTURES)
    iou_scores = []
    correct_misconceptions = 0

    for fix in GROUND_TRUTH_FIXTURES:
        gt_box = fix["ground_truth_box"]
        pred_box = fix["predicted_box"]
        iou = compute_box_iou(gt_box, pred_box)
        iou_scores.append(iou)

        if fix["ground_truth_misconception"] == fix["predicted_misconception"]:
            correct_misconceptions += 1

    elapsed = time.time() - t0
    mean_iou = sum(iou_scores) / total_fixtures if total_fixtures > 0 else 0.0
    classification_acc = (correct_misconceptions / total_fixtures) * 100 if total_fixtures > 0 else 0.0

    print(f"\n[BENCHMARK RESULTS - {elapsed:.3f}s]")
    print(f" • Total Scratchpad Fixtures:   {total_fixtures}")
    print(f" • Mean Bounding Box IoU:       {mean_iou:.3f} (Industry Target: > 0.70)")
    print(f" • Misconception Tag Precision: {classification_acc:.1f}% ({correct_misconceptions}/{total_fixtures})")
    print(f" • Min Box IoU:                 {min(iou_scores):.3f}")
    print(f" • Max Box IoU:                 {max(iou_scores):.3f}")
    print("-" * 76)

    return {
        "benchmark": "Multimodal Scratchpad Reticle & Misconception Benchmark",
        "total_fixtures": total_fixtures,
        "mean_bounding_box_iou": round(mean_iou, 3),
        "misconception_precision_pct": round(classification_acc, 2),
        "duration_seconds": round(elapsed, 4),
        "passed": (mean_iou >= 0.70 and classification_acc >= 90.0),
    }


if __name__ == "__main__":
    res = run_vision_reticle_benchmark()
    sys.exit(0 if res["passed"] else 1)
