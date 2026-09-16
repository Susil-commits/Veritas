"""
Seed database with problems + generate Gemini embeddings.
Supports expanded problem bank (200+ problems across 10 skills).
Features:
- Idempotent deduplication (checks existing titles in Supabase)
- Batch embedding generation via Gemini with retry/backoff
- Accurate metadata preservation (source: gsm8k vs hand_curated)
- Optional --clean flag to refresh table

Usage:
    python scripts/seed_db.py
    python scripts/seed_db.py --clean
"""
# pyright: reportMissingImports=false, reportMissingModuleSource=false
import os
import sys
import json
import time
import argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
if sys.platform == "win32":
    try:
        getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from pydantic import SecretStr
from db.supabase_client import get_supabase
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION

SEED_FILE = Path(__file__).parent.parent / "data" / "seed_problems.json"
BATCH_SIZE = 15


def embed_batch_with_retry(texts: list[str], embeddings_model, max_retries: int = 4) -> list[list[float]]:
    """Generate embeddings for a batch with exponential backoff on rate limits."""
    for attempt in range(max_retries):
        try:
            return embeddings_model.embed_documents(texts, output_dimensionality=EMBEDDING_DIMENSION)
        except Exception as e:
            err_str = str(e).lower()
            if attempt < max_retries - 1 and ("429" in err_str or "quota" in err_str or "resource" in err_str or "rate" in err_str):
                sleep_time = (2 ** attempt) * 2.5
                print(f"      ⏳ Rate limit encountered. Backing off for {sleep_time:.1f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(sleep_time)
            else:
                raise e
    return []


def main():
    parser = argparse.ArgumentParser(description="Seed problem bank into Supabase")
    parser.add_argument("--clean", action="store_true", help="Delete existing problems before seeding")
    args = parser.parse_args()

    print("🌱 Initializing Problem Bank Database Seeder...")
    supabase = get_supabase()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY is not set.")
        sys.exit(1)

    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=SecretStr(api_key),
    )

    if not SEED_FILE.exists():
        print(f"❌ Error: {SEED_FILE} does not exist. Run scripts/expand_problem_bank.py first.")
        sys.exit(1)

    with open(SEED_FILE, "r", encoding="utf-8") as f:
        problems = json.load(f)

    print(f"   Loaded {len(problems)} problems from {SEED_FILE.name}")

    # Fetch existing problems from database
    existing_res = supabase.table("problems").select("id, title, text, skill_id").execute()
    existing_rows = existing_res.data or []
    print(f"   Found {len(existing_rows)} existing problems in Supabase.")

    if args.clean:
        print("   🧹 Cleaning existing problems from Supabase...")
        try:
            # Delete in chunks
            for r in existing_rows:
                supabase.table("problems").delete().eq("id", r["id"]).execute()
            print("   ✅ Existing problems cleared.")
            existing_rows = []
        except Exception as e:
            print(f"   ⚠️ Could not delete all rows (may be referenced by session_events): {e}")

    existing_by_title = {r["title"].strip().lower(): r["id"] for r in existing_rows}
    to_insert = [p for p in problems if p["title"].strip().lower() not in existing_by_title]

    # Synchronize expected_steps for existing problems
    print(f"   🔄 Synchronizing clean expected_steps for {len(existing_rows)} existing problems in Supabase...")
    updated_count = 0
    for p in problems:
        t_key = p["title"].strip().lower()
        if t_key in existing_by_title:
            row_id = existing_by_title[t_key]
            try:
                supabase.table("problems").update({
                    "expected_steps": p["expected_steps"],
                    "difficulty": p["difficulty"],
                }).eq("id", row_id).execute()
                updated_count += 1
            except Exception as e:
                print(f"      ⚠️ Update failed for {p['title']}: {e}")
    print(f"   ✅ Synchronized expected_steps for {updated_count} problems.")

    print(f"   📥 Inserting {len(to_insert)} new problems with 768-dim embeddings...")

    inserted_count = 0
    for i in range(0, len(to_insert), BATCH_SIZE):
        batch = to_insert[i : i + BATCH_SIZE]
        embed_inputs = [f"{p['title']}: {p['text']}" for p in batch]

        try:
            batch_vectors = embed_batch_with_retry(embed_inputs, embeddings)
        except Exception as e:
            print(f"   ❌ Failed to generate embeddings for batch {i//BATCH_SIZE + 1}: {e}")
            continue

        rows_to_insert = []
        for p, vec in zip(batch, batch_vectors):
            rows_to_insert.append({
                "title": p["title"],
                "text": p["text"],
                "skill_id": p["skill_id"],
                "difficulty": p["difficulty"],
                "expected_steps": p["expected_steps"],
                "source": p.get("source", "hand_curated"),
                "embedding": vec,
            })

        try:
            supabase.table("problems").insert(rows_to_insert).execute()
            inserted_count += len(rows_to_insert)
            progress = min(i + BATCH_SIZE, len(to_insert))
            print(f"   [{progress}/{len(to_insert)}] ✅ Seeded batch of {len(rows_to_insert)} problems")
            # Polite pause to prevent per-minute rate-limit throttling
            time.sleep(1.0)
        except Exception as e:
            print(f"   ❌ Supabase insert error on batch {i//BATCH_SIZE + 1}: {e}")

    # Final database audit
    final_res = supabase.table("problems").select("skill_id, difficulty").execute()
    final_rows = final_res.data or []
    by_skill = Counter(r["skill_id"] for r in final_rows)

    print("\n" + "=" * 50)
    print("DATABASE SEEDING SUMMARY".center(50))
    print("=" * 50)
    print(f"Total problems currently in database: {len(final_rows)}")
    print(f"New problems inserted in this run: {inserted_count}")
    print("\nBreakdown by Skill:")
    for skill_id, count in sorted(by_skill.items()):
        print(f"   • {skill_id:<10}: {count} problems")
    print("=" * 50)
    print("✅ Database seeding complete!")


if __name__ == "__main__":
    main()
