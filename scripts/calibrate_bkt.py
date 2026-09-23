"""
BKT Model Calibration Utility.
Calibrates Bayesian Knowledge Tracing parameters (prior, learn, guess, slip)
against real student response sequences from the ASSISTments 2009-2010 benchmark dataset.

Usage:
    python scripts/calibrate_bkt.py --fit       # Fit BKT on real ASSISTments data & update parameters.json
    python scripts/calibrate_bkt.py --report    # Display calibration status table
    python scripts/calibrate_bkt.py --validate  # Run Bayesian monotonicity & dynamic checks
"""
import os
import sys
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from bkt.tracker import get_skill_params, update_mastery

PARAMS_FILE = BACKEND_DIR / "bkt" / "parameters.json"
DATA_FILE = ROOT_DIR / "data" / "assistments_sequences.json"


def split_sequences(
    sequences: list[list[int]],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> tuple[list[list[int]], list[list[int]], list[list[int]]]:
    """
    Student-level split: 70% Train, 15% Validation, 15% Held-out Test.
    Each element in `sequences` is the complete chronological response history of ONE distinct student.
    Grouping by student sequence guarantees that no individual interactions from the same student
    are split across train and test sets.
    Uses a seeded random shuffle to ensure representative student distribution across splits.
    """
    rng = random.Random(seed)
    shuffled = sequences.copy()
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    train_seqs = shuffled[:n_train]
    val_seqs = shuffled[n_train:n_train + n_val]
    test_seqs = shuffled[n_train + n_val:]
    return train_seqs, val_seqs, test_seqs


def fit_bkt_mle(
    sequences: list[list[int]],
    val_sequences: list[list[int]] | None = None,
    sample_limit: int | None = None,
) -> dict:
    """
    Fit BKT parameters (prior, learn, guess, slip) on real student response sequences
    using maximum likelihood estimation over bounded parameter grid on train sequences,
    with hyperparameter model selection calibrated against the validation split
    (Corbett & Anderson 1995; Baker, Corbett & Aleven 2008).
    If sample_limit is None, fits across all eligible training sequences.
    """
    # Grid bounded by standard cognitive tutoring psychometrics
    priors = [0.15, 0.22, 0.28, 0.35, 0.40]
    learns = [0.08, 0.12, 0.16, 0.20, 0.24]
    guesses = [0.12, 0.18, 0.22, 0.26]
    slips = [0.05, 0.08, 0.11, 0.14]

    train_sample = sequences[:sample_limit] if sample_limit is not None else sequences
    val_sample = val_sequences[:sample_limit] if (val_sequences and sample_limit is not None) else val_sequences

    # Step 1: Compute train negative log-likelihood across all grid points
    candidate_fits: list[tuple[float, dict]] = []
    for p in priors:
        for l in learns:
            for g in guesses:
                for s in slips:
                    neg_log_lik = 0.0
                    for seq in train_sample:
                        mastery = p
                        for obs in seq:
                            p_corr = mastery * (1.0 - s) + (1.0 - mastery) * g
                            p_obs = p_corr if obs == 1 else (1.0 - p_corr)
                            p_obs = max(p_obs, 1e-5)
                            neg_log_lik -= math.log(p_obs)

                            # Posterior probability given observation
                            num = mastery * (1.0 - s) if obs == 1 else mastery * s
                            denom = p_obs
                            p_known = num / denom if denom > 0 else mastery
                            mastery = p_known + (1.0 - p_known) * l
                            mastery = min(max(mastery, 0.0), 1.0)

                    candidate_fits.append((
                        neg_log_lik,
                        {
                            "prior": round(p, 2),
                            "learn": round(l, 2),
                            "guess": round(g, 2),
                            "slip": round(s, 2),
                        }
                    ))

    candidate_fits.sort(key=lambda x: x[0])

    # Step 2: If validation split is provided, select optimal model minimizing validation loss among top candidates
    if val_sample and len(val_sample) > 0:
        top_candidates = [c[1] for c in candidate_fits[:10]]
        best_val_loss = float("inf")
        best_model = top_candidates[0]
        for cand in top_candidates:
            val_loss = 0.0
            n_val_obs = 0
            for seq in val_sample:
                m = cand["prior"]
                for obs in seq:
                    p_corr = m * (1.0 - cand["slip"]) + (1.0 - m) * cand["guess"]
                    p_obs = p_corr if obs == 1 else (1.0 - p_corr)
                    p_obs = max(p_obs, 1e-5)
                    val_loss -= math.log(p_obs)
                    n_val_obs += 1

                    num = m * (1.0 - cand["slip"]) if obs == 1 else m * cand["slip"]
                    denom = p_obs
                    p_known = num / denom if denom > 0 else m
                    m = p_known + (1.0 - p_known) * cand["learn"]
                    m = min(max(m, 0.0), 1.0)
            avg_val_loss = val_loss / max(1, n_val_obs)
            if avg_val_loss < best_val_loss:
                best_val_loss = avg_val_loss
                best_model = cand
        return best_model

    return candidate_fits[0][1]


@dataclass
class CalibrationBucket:
    range_label: str
    lower: float
    upper: float
    preds: list[float] = field(default_factory=list)
    actuals: list[int] = field(default_factory=list)


def evaluate_bkt_predictive_performance(
    sequences: list[list[int]],
    prior: float,
    learn: float,
    guess: float,
    slip: float,
) -> dict:
    """
    Evaluate BKT predictive accuracy and calibration on held-out student response sequences.
    Computes Log Loss (Binary Cross-Entropy), Brier Score (MSE on probability),
    Accuracy (0.5 threshold), and 5-bin calibration curve.
    """
    preds: list[float] = []
    actuals: list[int] = []

    for seq in sequences:
        mastery = prior
        for obs in seq:
            # Predict P(Correct_t) before seeing observation
            p_corr = mastery * (1.0 - slip) + (1.0 - mastery) * guess
            p_corr = min(max(p_corr, 1e-6), 1.0 - 1e-6)
            preds.append(p_corr)
            actuals.append(obs)

            # Posterior update given observation
            p_obs = p_corr if obs == 1 else (1.0 - p_corr)
            num = mastery * (1.0 - slip) if obs == 1 else mastery * slip
            p_known = num / p_obs if p_obs > 0 else mastery
            mastery = p_known + (1.0 - p_known) * learn
            mastery = min(max(mastery, 0.0), 1.0)

    n = len(actuals)
    if n == 0:
        return {"log_loss": 0.0, "brier_score": 0.0, "accuracy": 0.0, "count": 0, "calibration_bins": []}

    log_loss = -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(preds, actuals)) / n
    brier = sum((p - y) ** 2 for p, y in zip(preds, actuals)) / n
    acc = sum((p >= 0.5) == y for p, y in zip(preds, actuals)) / n

    # Calibration Curve (5 probability buckets)
    buckets = [
        CalibrationBucket("0.0 - 0.2", 0.0, 0.2),
        CalibrationBucket("0.2 - 0.4", 0.2, 0.4),
        CalibrationBucket("0.4 - 0.6", 0.4, 0.6),
        CalibrationBucket("0.6 - 0.8", 0.6, 0.8),
        CalibrationBucket("0.8 - 1.0", 0.8, 1.01),
    ]
    for p, y in zip(preds, actuals):
        for b in buckets:
            if b.lower <= p < b.upper:
                b.preds.append(p)
                b.actuals.append(y)
                break

    cal_curve = []
    for b in buckets:
        count = len(b.preds)
        mean_pred = sum(b.preds) / count if count > 0 else 0.0
        mean_actual = sum(b.actuals) / count if count > 0 else 0.0
        cal_curve.append({
            "bin": b.range_label,
            "count": count,
            "mean_predicted": round(mean_pred, 4),
            "observed_accuracy": round(mean_actual, 4),
            "calibration_error": round(abs(mean_pred - mean_actual), 4),
        })

    return {
        "log_loss": round(log_loss, 4),
        "brier_score": round(brier, 4),
        "accuracy": round(acc, 4),
        "total_observations": n,
        "calibration_curve": cal_curve,
    }


def run_fit(sample_limit: int | None = 300):
    """Fit real ASSISTments student interaction logs and update parameters.json."""
    if not DATA_FILE.exists():
        print(f"Data file not found at {DATA_FILE}. Running download...")
        import download_assistments
        download_assistments.main()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        assist_data = json.load(f)

    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        params_data = json.load(f)

    pilot_tag = f" (pilot limit: {sample_limit} seqs/skill)" if sample_limit else " (full dataset)"
    print(f"Fitting BKT parameters on real ASSISTments response sequences{pilot_tag}...")
    calibrated_map = {}
    for sid, info in assist_data.get("skills", {}).items():
        seqs = info["sequences"]
        train_seqs, val_seqs, test_seqs = split_sequences(seqs)
        fitted = fit_bkt_mle(train_seqs, val_sequences=val_seqs, sample_limit=sample_limit)
        calibrated_map[sid] = {
            "params": fitted,
            "assist_name": info["assistments_skill_name"],
            "students": info["total_students"],
            "observations": info["total_observations"],
            "train_count": len(train_seqs),
            "val_count": len(val_seqs),
            "test_count": len(test_seqs),
        }
        print(f"   ✓ {sid} ({info['skill_name']}):")
        print(f"     Prior={fitted['prior']}, Learn={fitted['learn']}, Guess={fitted['guess']}, Slip={fitted['slip']}")
        print(f"     Fitted on {len(train_seqs)} train seqs, calibrated on {len(val_seqs)} val seqs (from {info['total_students']} students, {info['total_observations']} responses)")

    # Update parameters.json
    for skill in params_data.get("skills", []):
        sid = skill["id"]
        if sid in calibrated_map:
            fit_info = calibrated_map[sid]
            skill.update(fit_info["params"])
            skill["calibrated"] = True
            skill["source"] = f"ASSISTments 2009-2010 ({fit_info['assist_name']})"
            actual_fit_count = min(sample_limit, fit_info["train_count"]) if sample_limit else fit_info["train_count"]
            limit_desc = f"pilot MLE fit on {actual_fit_count} sequences" if sample_limit else f"full train set fit on {actual_fit_count} sequences"
            skill["notes"] = f"{limit_desc} (70% train / 15% validation model selection from {fit_info['students']} students, {fit_info['observations']} total ASSISTments responses)"
        else:
            skill["calibrated"] = False
            skill["source"] = "Corbett & Anderson Baseline"
            skill["notes"] = "Cognitive Tutor default baseline parameters; real-data calibration scheduled for next phase"

    params_data["_metadata"] = {
        "description": "Bayesian Knowledge Tracing (BKT) skill parameter registry",
        "primary_calibration_source": "ASSISTments 2009-2010 Skill Builder Dataset (WPI / CAHLR)",
        "baseline_source": "Corbett & Anderson (1995) Standard Cognitive Tutor Priors",
        "calibration_method": "Maximum Likelihood Estimation on 70% Train with Hyperparameter Model Selection on 15% Validation",
        "data_split": {
            "train": "70% (likelihood estimation over parameter grid)",
            "validation": "15% (hyperparameter model selection & loss minimization)",
            "test": "15% (unbiased held-out predictive evaluation)"
        },
        "pilot_calibration_sample": f"{sample_limit} sequences/skill pilot grid MLE" if sample_limit else "full dataset sequences fit",
        "evaluation_metrics": ["Log Loss (Binary Cross-Entropy)", "Brier Score", "Accuracy", "Calibration Curve"],
        "last_calibrated": "2026-09-17"
    }

    with open(PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(params_data, f, indent=2)

    print(f"\n✅ Successfully updated {PARAMS_FILE} with real fitted parameters!\n")


def generate_calibration_report():
    """Print the current calibration report comparing calibrated skills vs baseline."""
    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("_metadata", {})
    skills = data.get("skills", [])

    print("\n" + "=" * 80)
    print("📊 VERITAS — BAYESIAN KNOWLEDGE TRACING (BKT) CALIBRATION REPORT")
    print("=" * 80)
    print(f"Primary Benchmark : {meta.get('primary_calibration_source', 'N/A')}")
    print(f"Baseline Standard : {meta.get('baseline_source', 'N/A')}")
    print(f"Method            : {meta.get('calibration_method', 'N/A')}")
    print(f"Last Calibrated   : {meta.get('last_calibrated', 'N/A')}")
    print("-" * 80)
    print(f"{'SKILL ID':<10} {'STATUS':<14} {'PRIOR':<7} {'LEARN':<7} {'GUESS':<7} {'SLIP':<7} {'SOURCE'}")
    print("-" * 80)

    calibrated_count = 0
    for s in skills:
        is_cal = s.get("calibrated", False)
        status = "[CALIBRATED]" if is_cal else "[BASELINE]"
        if is_cal:
            calibrated_count += 1
        source = s.get("source", "Default")
        print(f"{s['id']:<10} {status:<14} {s['prior']:<7.2f} {s['learn']:<7.2f} {s['guess']:<7.2f} {s['slip']:<7.2f} {source}")

    print("-" * 80)
    print(f"Total Skills: {len(skills)} | Calibrated on ASSISTments: {calibrated_count} ({calibrated_count/len(skills)*100:.0f}%) | Baseline: {len(skills)-calibrated_count}")
    print("=" * 80 + "\n")


def validate_bkt_dynamics():
    """Validate that knowledge tracing follows monotonicity and expected convergence."""
    print("🔬 Validating Bayesian update dynamics on real-calibrated skill '6.EE.B.7'...")
    skill_id = "6.EE.B.7"
    params = get_skill_params(skill_id)
    print(f"   Parameters: {params}")

    # Case 1: Consistent correct answers should increase mastery towards 1.0
    m = params["prior"]
    trace_correct = [m]
    for _ in range(4):
        m = update_mastery(m, is_correct=True, skill_id=skill_id)
        trace_correct.append(m)

    print(f"   4 consecutive correct steps: {' -> '.join(f'{x*100:.0f}%' for x in trace_correct)}")
    assert trace_correct[-1] > trace_correct[0], "Mastery must strictly increase on correct steps"

    # Case 2: Mistakes decrease or dampen mastery
    m_after_wrong = update_mastery(trace_correct[-1], is_correct=False, skill_id=skill_id)
    print(f"   Subsequent error step:       {trace_correct[-1]*100:.0f}% -> {m_after_wrong*100:.0f}%")
    assert m_after_wrong < trace_correct[-1], "Mastery must drop after an incorrect step"

    print("✅ BKT update dynamics verified successfully!\n")


def run_predictive_evaluation() -> dict:
    """
    Run empirical predictive evaluation of Calibrated BKT vs. Uncalibrated Baseline
    on the held-out 15% test sequence split.
    Reports Log Loss, Brier Score, Accuracy, and Reliability Calibration Curve.
    """
    if not DATA_FILE.exists():
        print(f"Data file not found at {DATA_FILE}. Running download...")
        import download_assistments
        download_assistments.main()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        assist_data = json.load(f)

    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        params_data = json.load(f)

    print("\n" + "=" * 90)
    print("📈 BKT PREDICTIVE PERFORMANCE & CALIBRATION BENCHMARK (HELD-OUT 15% TEST SET)")
    print("=" * 90)
    print(f"{'SKILL ID':<10} {'TEST N':<8} {'BASE BRIER':<11} {'CAL BRIER':<11} {'BASE LOGLOSS':<13} {'CAL LOGLOSS':<13} {'BASE ACC':<9} {'CAL ACC'}")
    print("-" * 90)

    baseline_params = {"prior": 0.30, "learn": 0.15, "guess": 0.20, "slip": 0.10}
    skill_evaluations = {}

    tot_test_obs = 0
    tot_base_brier = 0.0
    tot_cal_brier = 0.0
    tot_base_ll = 0.0
    tot_cal_ll = 0.0

    for sid, info in assist_data.get("skills", {}).items():
        seqs = info["sequences"]
        train_seqs, val_seqs, test_seqs = split_sequences(seqs)
        skill_cfg = next((s for s in params_data.get("skills", []) if s["id"] == sid), None)
        if not skill_cfg:
            continue

        base_res = evaluate_bkt_predictive_performance(test_seqs, **baseline_params)
        cal_res = evaluate_bkt_predictive_performance(
            test_seqs,
            prior=skill_cfg["prior"],
            learn=skill_cfg["learn"],
            guess=skill_cfg["guess"],
            slip=skill_cfg["slip"],
        )

        n_obs = cal_res["total_observations"]
        tot_test_obs += n_obs
        tot_base_brier += base_res["brier_score"] * n_obs
        tot_cal_brier += cal_res["brier_score"] * n_obs
        tot_base_ll += base_res["log_loss"] * n_obs
        tot_cal_ll += cal_res["log_loss"] * n_obs

        skill_evaluations[sid] = {
            "test_observations": n_obs,
            "baseline": base_res,
            "calibrated": cal_res,
        }

        b_br, c_br = base_res["brier_score"], cal_res["brier_score"]
        b_ll, c_ll = base_res["log_loss"], cal_res["log_loss"]
        b_acc, c_acc = base_res["accuracy"], cal_res["accuracy"]
        print(f"{sid:<10} {n_obs:<8} {b_br:<11.4f} {c_br:<11.4f} {b_ll:<13.4f} {c_ll:<13.4f} {b_acc*100:<8.1f}% {c_acc*100:.1f}%")

    avg_base_brier = tot_base_brier / tot_test_obs if tot_test_obs > 0 else 0.0
    avg_cal_brier = tot_cal_brier / tot_test_obs if tot_test_obs > 0 else 0.0
    avg_base_ll = tot_base_ll / tot_test_obs if tot_test_obs > 0 else 0.0
    avg_cal_ll = tot_cal_ll / tot_test_obs if tot_test_obs > 0 else 0.0

    print("-" * 90)
    print(f"{'OVERALL':<10} {tot_test_obs:<8} {avg_base_brier:<11.4f} {avg_cal_brier:<11.4f} {avg_base_ll:<13.4f} {avg_cal_ll:<13.4f}")
    brier_impr = (avg_base_brier - avg_cal_brier) / avg_base_brier * 100 if avg_base_brier > 0 else 0.0
    ll_impr = (avg_base_ll - avg_cal_ll) / avg_base_ll * 100 if avg_base_ll > 0 else 0.0
    print(f"🎯 Relative Predictive Improvement: Brier Score: -{brier_impr:.2f}% MSE | Log Loss: -{ll_impr:.2f}% Cross-Entropy")
    print("=" * 90)

    # Print Reliability / Calibration Curve Sample for top skill 6.EE.B.7
    sample_skill = "6.EE.B.7"
    if sample_skill in skill_evaluations:
        print(f"\n📊 Reliability Diagram (Calibration Curve) for {sample_skill}:")
        print(f"{'BIN PROBABILITY':<18} {'OBSERVATIONS':<14} {'MEAN PREDICTED':<16} {'OBSERVED ACCURACY':<18} {'CAL ERROR'}")
        print("-" * 80)
        for b in skill_evaluations[sample_skill]["calibrated"]["calibration_curve"]:
            print(f"{b['bin']:<18} {b['count']:<14} {b['mean_predicted']:<16.4f} {b['observed_accuracy']:<18.4f} {b['calibration_error']:.4f}")
        print("-" * 80 + "\n")

    return {
        "overall": {
            "total_test_observations": tot_test_obs,
            "baseline_brier": round(avg_base_brier, 4),
            "calibrated_brier": round(avg_cal_brier, 4),
            "baseline_log_loss": round(avg_base_ll, 4),
            "calibrated_log_loss": round(avg_cal_ll, 4),
            "brier_improvement_pct": round(brier_impr, 2),
            "log_loss_improvement_pct": round(ll_impr, 2),
        },
        "skills": skill_evaluations,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Calibrate and inspect BKT parameters.")
    parser.add_argument("--fit", action="store_true", help="Fit parameters on real ASSISTments data.")
    parser.add_argument("--sample-limit", type=int, default=300, help="Max sequences per skill to fit (default 300 for pilot; use 0 or --full for all)")
    parser.add_argument("--full", action="store_true", help="Fit across all eligible training sequences without pilot limit.")
    parser.add_argument("--evaluate", action="store_true", help="Run predictive evaluation on held-out test split (Log Loss, Brier Score, Accuracy).")
    parser.add_argument("--validate", action="store_true", help="Run dynamic validation tests.")
    parser.add_argument("--report", action="store_true", help="Print calibration status report.")
    args = parser.parse_args()

    limit = None if args.full or args.sample_limit == 0 else args.sample_limit

    if args.fit:
        run_fit(sample_limit=limit)
        generate_calibration_report()
        run_predictive_evaluation()
        validate_bkt_dynamics()
    elif args.evaluate:
        run_predictive_evaluation()
    elif args.report:
        generate_calibration_report()
    elif args.validate:
        validate_bkt_dynamics()
    else:
        # Default behavior: report, evaluate, and validate
        generate_calibration_report()
        run_predictive_evaluation()
        validate_bkt_dynamics()


if __name__ == "__main__":
    main()
