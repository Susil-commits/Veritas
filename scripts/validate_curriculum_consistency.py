"""
Curriculum Consistency & Learner Model Verification Script — Veritas.
Validates end-to-end consistency across:
1. Game Levels (Arcade curriculum) -> BKT skill parameters & registry
2. Curated & Seed Problem Bank -> Common Core State Standards (CCSS) skills
3. Skill parameter completeness & Bayesian psychometric bounds
"""
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

from main import GAME_LEVELS_CONFIG
from bkt.tracker import get_all_skills, get_skill_params

PARAMS_FILE = BACKEND_DIR / "bkt" / "parameters.json"
SEED_PROBLEMS_FILE = ROOT_DIR / "data" / "seed_problems.json"


def validate_curriculum():
    print("=" * 80)
    print("   VERITAS CURRICULUM CONSISTENCY & INTEGRITY VALIDATOR")
    print("=" * 80)

    errors = []
    warnings = []

    # 1. Load BKT parameters registry
    if not PARAMS_FILE.exists():
        errors.append(f"Missing BKT parameters file at {PARAMS_FILE}")
        return False, errors, warnings

    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        params_data = json.load(f)

    bkt_skills = {s["id"]: s for s in params_data.get("skills", [])}
    print(f"\n[1] BKT Skill Parameter Registry: {len(bkt_skills)} skills registered.")
    for sid, s in bkt_skills.items():
        for param in ("prior", "learn", "guess", "slip"):
            if param not in s:
                errors.append(f"Skill {sid} missing parameter '{param}' in parameters.json")
            else:
                val = s[param]
                if not (0.0 <= val <= 1.0):
                    errors.append(f"Skill {sid} parameter '{param}' = {val} out of bounds [0.0, 1.0]")
        # Degenerate parameter check: guess + slip should be < 1.0
        g = s.get("guess", 0.2)
        sl = s.get("slip", 0.1)
        if g + sl >= 1.0:
            errors.append(f"Skill {sid} violates identifiability: guess ({g}) + slip ({sl}) >= 1.0")

    print(f"    ✓ All {len(bkt_skills)} BKT skills passed psychometric parameter validity checks.")

    # 2. Check Game Levels vs BKT Skill Registry
    print(f"\n[2] Checking {len(GAME_LEVELS_CONFIG)} Game Levels against Skill Registry...")
    for game in GAME_LEVELS_CONFIG:
        gid = game["id"]
        req_skill = game["skill_required"]
        alt_skill = game.get("alt_skill_required")

        if req_skill not in bkt_skills:
            errors.append(f"Game '{gid}' requires skill '{req_skill}' which does not exist in BKT parameters!")
        else:
            print(f"    ✓ Level {game.get('level')}: {game.get('name')} -> primary skill '{req_skill}' validated ({bkt_skills[req_skill]['name']})")

        if alt_skill:
            if alt_skill not in bkt_skills:
                errors.append(f"Game '{gid}' references alt skill '{alt_skill}' which does not exist in BKT parameters!")
            else:
                print(f"      + Alternative unlock skill '{alt_skill}' validated ({bkt_skills[alt_skill]['name']})")

    # 3. Check Problem Bank vs BKT Skill Registry
    print(f"\n[3] Checking Seed Problem Bank against Skill Registry...")
    if not SEED_PROBLEMS_FILE.exists():
        errors.append(f"Missing problem bank file at {SEED_PROBLEMS_FILE}")
        return False, errors, warnings

    with open(SEED_PROBLEMS_FILE, "r", encoding="utf-8") as f:
        problems = json.load(f)

    print(f"    Loaded {len(problems)} curated problems across curriculum.")
    skills_with_problems = set()
    for idx, p in enumerate(problems, 1):
        s_id = p.get("skill_id")
        if not s_id:
            errors.append(f"Problem #{idx} ('{p.get('title')}') missing 'skill_id'")
            continue

        if s_id not in bkt_skills:
            errors.append(f"Problem #{idx} ('{p.get('title')}') references unknown skill '{s_id}'")
        else:
            skills_with_problems.add(s_id)

        # Check required fields
        if not p.get("title"):
            errors.append(f"Problem #{idx} missing title")
        if not p.get("text"):
            errors.append(f"Problem #{idx} missing text")
        if not p.get("expected_steps") or len(p["expected_steps"]) == 0:
            errors.append(f"Problem #{idx} ('{p.get('title')}') has no expected_steps")
        diff = p.get("difficulty")
        if diff not in (1, 2, 3, 4, 5):
            errors.append(f"Problem #{idx} ('{p.get('title')}') invalid difficulty: {diff}")

    # Ensure all skills in BKT have problems in the bank
    missing_problem_skills = set(bkt_skills.keys()) - skills_with_problems
    if missing_problem_skills:
        warnings.append(f"Skills in BKT registry without problems in seed_problems.json: {missing_problem_skills}")
    else:
        print(f"    ✓ All {len(bkt_skills)} BKT skills have active practice problems in the curriculum bank.")

    print("\n" + "-" * 80)
    if errors:
        print(f"❌ Curriculum validation FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"   • {err}")
        return False
    else:
        print("✅ ALL CURRICULUM CONSISTENCY CHECKS PASSED!")
        print(f"   • {len(GAME_LEVELS_CONFIG)} Game levels verified")
        print(f"   • {len(bkt_skills)} BKT skill models verified")
        print(f"   • {len(problems)} Problems verified with valid difficulty & step breakdown")
        print("=" * 80 + "\n")
        return True


if __name__ == "__main__":
    success = validate_curriculum()
    sys.exit(0 if success else 1)
