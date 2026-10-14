"""
Generate and persist 768-dim Gemini embeddings for all 208 problems in data/seed_problems.json.
This enables fast offline pgvector evaluation and eliminates per-query embedding overhead.
"""
import os
import sys
import json
import time
from pathlib import Path

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

from agents.content_agent import embed_text

SEED_FILE = ROOT_DIR / "data" / "seed_problems.json"
OUT_FILE = ROOT_DIR / "data" / "problem_embeddings.json"


def main():
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        problems = json.load(f)

    print(f"Loaded {len(problems)} problems from {SEED_FILE}")

    existing_embeddings = {}
    if OUT_FILE.exists():
        try:
            with open(OUT_FILE, "r", encoding="utf-8") as f:
                existing_embeddings = json.load(f)
            print(f"Loaded {len(existing_embeddings)} existing embeddings from cache.")
        except Exception:
            existing_embeddings = {}

    updated = False
    for i, p in enumerate(problems, 1):
        title = p.get("title", "")
        text = p.get("text", "")
        key = title.strip()
        if key in existing_embeddings and len(existing_embeddings[key]) == 768:
            continue

        embed_input = f"{title}: {text}"
        vec = embed_text(embed_input)
        existing_embeddings[key] = vec
        updated = True
        if i % 10 == 0 or i == len(problems):
            print(f"[{i}/{len(problems)}] Embedded: {title[:30]} (dim={len(vec)})")
            # Save incrementally
            with open(OUT_FILE, "w", encoding="utf-8") as f:
                json.dump(existing_embeddings, f)
            time.sleep(0.2)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_embeddings, f)

    print(f"\n[DONE] Saved {len(existing_embeddings)} problem embeddings to {OUT_FILE}")


if __name__ == "__main__":
    main()
