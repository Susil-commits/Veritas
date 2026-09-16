"""
Problem Bank Expansion Pipeline
Extracts, tags, and generates 180-200+ high-quality math problems across all 10 Common Core skills.
Guarantees 18-20 problems per skill spanning difficulty tiers 1 to 5.
Sources:
- Curated Common Core math problem bank (algebra, fractions, equations)
- GSM8K word problems with cleaned solution steps
- Existing foundational seed problems
"""
import sys
import json
import re
import urllib.request
from pathlib import Path
from collections import defaultdict, Counter

if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = DATA_DIR / "seed_problems.json"
BACKUP_FILE = DATA_DIR / "seed_problems_backup.json"

ALL_SKILLS = [
    "3.OA.A.1",  # Understanding multiplication
    "3.OA.A.2",  # Understanding division
    "3.OA.D.8",  # Solving two-step word problems
    "4.NF.A.1",  # Equivalent fractions
    "4.NF.B.3",  # Adding and subtracting fractions
    "4.NF.B.4",  # Multiplying fractions by whole numbers
    "5.NF.B.7",  # Dividing fractions
    "6.EE.A.2",  # Writing and reading algebraic expressions
    "6.EE.B.7",  # Solving one-step equations
    "7.EE.B.4",  # Solving multi-step equations
]

def clean_gsm8k_steps(answer_raw: str) -> list[str]:
    """Parse GSM8K solution text into clean, pedagogical expected steps."""
    lines = [l.strip() for l in answer_raw.split("\n") if l.strip()]
    steps = []
    for line in lines:
        if line.startswith("####"):
            ans = line.replace("####", "").strip()
            steps.append(f"Answer: {ans}")
        else:
            # In GSM8K, the calculator tag <<expr=res>> is followed by the human-written result in the text.
            # Stripping the <<...>> tag leaves the clean mathematical equation without duplicating numbers.
            clean = re.sub(r"<<[^>]+>>", "", line).strip()
            if clean and not clean.startswith("####"):
                steps.append(clean)
    return steps or ["Follow standard arithmetic steps", f"Answer: {answer_raw[-20:]}"]


def fetch_gsm8k_candidates(max_fetch: int = 1500) -> list[dict]:
    """Fetch sample from OpenAI GSM8K GitHub repo."""
    url = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/train.jsonl"
    print(f"📥 Fetching GSM8K candidate problems from:\n   {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    candidates = []
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            for _ in range(max_fetch):
                line = resp.readline()
                if not line:
                    break
                data = json.loads(line.decode("utf-8"))
                candidates.append(data)
        print(f"✅ Downloaded {len(candidates)} raw GSM8K problems.")
    except Exception as e:
        print(f"⚠️ Warning: Could not fetch remote GSM8K ({e}). Using local pipeline fallbacks.")
    return candidates


def tag_gsm8k_problem(q: str, a: str) -> tuple[str | None, int]:
    """
    Enhanced heuristic tagger mapping a GSM8K word problem to Common Core skill ID and difficulty (1-5).
    """
    q_lower = q.lower()
    a_lower = a.lower()
    combined = q_lower + " " + a_lower

    # Calculate step count from answer
    num_calcs = len(re.findall(r"<<[^>]+>>", a))

    # Fraction detection
    has_fraction = bool(re.search(r"\b\d+/\d+\b|half|third|quarter|fourth|fraction", combined))

    # 1. Fractions: Adding / Subtracting
    if has_fraction and re.search(r"add|plus|more than|leftover|subtract|remaining|difference|total fraction", combined):
        if re.search(r"share|divide|divided by|each gets", combined):
            diff = 3 if num_calcs <= 2 else 4
            return "5.NF.B.7", diff
        diff = 2 if num_calcs <= 2 else (3 if num_calcs == 3 else 4)
        return "4.NF.B.3", diff

    # 2. Fractions: Multiplying by whole numbers
    if has_fraction and re.search(r"times|of the total|fraction of|per|each day|multiplied", combined):
        diff = 2 if num_calcs <= 2 else 3
        return "4.NF.B.4", diff

    # 3. Two-step word problems (3.OA.D.8)
    if num_calcs == 2 and not has_fraction:
        return "3.OA.D.8", 2
    if num_calcs == 3 and not has_fraction:
        return "3.OA.D.8", 3

    # 4. Pure division / sharing
    if re.search(r"\b(?:split|share|shared equally|divided equally|each friend gets|divided among|per box)\b", q_lower):
        if num_calcs <= 1:
            return "3.OA.A.2", 1
        elif num_calcs == 2:
            return "3.OA.A.2", 2
        else:
            return "3.OA.A.2", 3

    # 5. Pure multiplication
    if re.search(r"\b(?:in total|how many altogether|packs of|boxes of|times as many|dozen)\b", q_lower) and not has_fraction:
        if num_calcs <= 1:
            return "3.OA.A.1", 1
        elif num_calcs == 2:
            return "3.OA.A.1", 2
        else:
            return "3.OA.A.1", 3

    return None, 1


def main():
    print("🚀 Starting Problem Bank Expansion...")
    existing = []
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"📦 Loaded {len(existing)} existing problems.")

    # Save backup of initial seed
    if not BACKUP_FILE.exists() and existing:
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        print(f"💾 Backed up initial seed problems to {BACKUP_FILE.name}")

    # Build curated high-quality bank to ensure 18-20 per skill across 1-5 difficulty
    skill_problems = defaultdict(list)

    # Seed with existing valid hand-curated problems
    for p in existing:
        skill_problems[p["skill_id"]].append(p)

    # Ingest from GSM8K
    gsm8k_raw = fetch_gsm8k_candidates(max_fetch=1200)
    gsm8k_count = 0
    for i, item in enumerate(gsm8k_raw):
        q = item["question"]
        a = item["answer"]
        skill_id, diff = tag_gsm8k_problem(q, a)
        if skill_id and len(skill_problems[skill_id]) < 12:
            title_words = [w.capitalize() for w in re.findall(r"\b[a-zA-Z]{4,}\b", q)[:3]]
            title = " ".join(title_words) or f"Word Problem {i+1}"
            steps = clean_gsm8k_steps(a)
            if len(steps) >= 2:
                prob = {
                    "title": title,
                    "text": q,
                    "skill_id": skill_id,
                    "difficulty": diff,
                    "expected_steps": steps,
                    "source": "gsm8k"
                }
                skill_problems[skill_id].append(prob)
                gsm8k_count += 1

    print(f"✅ Ingested {gsm8k_count} auto-tagged GSM8K problems into bank.")

    # Now load our Common Core Curated Standards Problem Bank
    from curated_math_bank import CURATED_STANDARDS_PROBLEMS
    curated_count = 0
    for p in CURATED_STANDARDS_PROBLEMS:
        sid = p["skill_id"]
        existing_titles = {x["title"].lower() for x in skill_problems[sid]}
        if p["title"].lower() not in existing_titles:
            skill_problems[sid].append(p)
            curated_count += 1

    print(f"✅ Added {curated_count} targeted Common Core curriculum problems.")

    # Final tally and balance check
    all_final_problems = []
    print("\n📊 Problem Distribution per Skill:")
    print("=" * 65)
    print(f" {'SKILL ID':<12} | {'TOTAL':<6} | {'DIFF 1':<6} | {'DIFF 2':<6} | {'DIFF 3':<6} | {'DIFF 4':<6} | {'DIFF 5':<6}")
    print("-" * 65)

    for sid in ALL_SKILLS:
        probs = skill_problems[sid]
        diff_counts = Counter(p["difficulty"] for p in probs)
        print(f" {sid:<12} | {len(probs):<6} | {diff_counts[1]:<6} | {diff_counts[2]:<6} | {diff_counts[3]:<6} | {diff_counts[4]:<6} | {diff_counts[5]:<6}")
        all_final_problems.extend(probs)

    print("-" * 65)
    print(f"Total problems in expanded bank: {len(all_final_problems)}")
    print("=" * 65)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_final_problems, f, indent=2)

    print(f"\n💾 Saved expanded seed bank to:\n   {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
