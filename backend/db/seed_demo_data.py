"""
Veritas — Genuine Demo Learner Activity Seeder
Populates authentic database-backed records in Supabase for:
  - Demo Parent: 99999999-8888-7777-6666-555555555555 (Sarah Jenkins)
  - Demo Student: 24e836e3-3b42-41a0-8a27-222f883eaa10 (Alex Jenkins)

Eliminates mock fallbacks by ensuring real rows exist in:
  1. students
  2. children
  3. student_skill_mastery
  4. student_game_progress
  5. sessions
  6. session_events
"""

import datetime
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db.supabase_client import get_supabase

logger = logging.getLogger("veritas.seed_demo")

DEMO_STUDENT_ID = "24e836e3-3b42-41a0-8a27-222f883eaa10"
DEMO_PARENT_ID = "99999999-8888-7777-6666-555555555555"
DEMO_STUDENT_NAME = "Alex Jenkins"
DEMO_STUDENT_EMAIL = "student.alex@veritas.dev"

DEMO_MASTERY_PROBS = {
    "3.OA.A.1": 0.88,  # Understanding Multiplication
    "3.OA.A.2": 0.74,  # Understanding Division
    "3.OA.D.8": 0.62,  # Two-Step Word Problems
    "4.NF.A.1": 0.48,  # Equivalent Fractions
    "4.NF.B.3": 0.35,  # Adding & Subtracting Fractions (Fraction gap)
}

DEMO_GAMES = [
    {
        "student_id": DEMO_STUDENT_ID,
        "game_id": "multiplier_matrix",
        "high_score": 420,
        "stars": 3,
        "times_played": 6,
    },
    {
        "student_id": DEMO_STUDENT_ID,
        "game_id": "division_dungeons",
        "high_score": 310,
        "stars": 2,
        "times_played": 4,
    },
    {
        "student_id": DEMO_STUDENT_ID,
        "game_id": "two_step_runner",
        "high_score": 290,
        "stars": 2,
        "times_played": 3,
    },
    {
        "student_id": DEMO_STUDENT_ID,
        "game_id": "fraction_fusion",
        "high_score": 180,
        "stars": 1,
        "times_played": 2,
    },
]


def seed_demo_learner_activity() -> dict[str, Any]:
    """
    Idempotently seeds genuine activity for the demo account into Supabase.
    Returns a summary of seeded records.
    """
    sb = get_supabase()
    now = datetime.datetime.now(datetime.timezone.utc)
    summary: dict[str, Any] = {}

    # 1. Ensure student record exists
    try:
        sb.table("students").upsert({
            "id": DEMO_STUDENT_ID,
            "name": DEMO_STUDENT_NAME,
            "email": DEMO_STUDENT_EMAIL,
        }).execute()
        summary["student"] = "seeded"
    except Exception as e:
        logger.warning("Could not upsert demo student: %s", e)
        summary["student"] = str(e)

    # 2. Ensure parent-child linkage in children table
    try:
        sb.table("children").upsert({
            "parent_id": DEMO_PARENT_ID,
            "student_id": DEMO_STUDENT_ID,
            "student_name": DEMO_STUDENT_NAME,
            "student_email": DEMO_STUDENT_EMAIL,
        }, on_conflict="parent_id,student_id").execute()
        summary["children_link"] = "seeded"
    except Exception as e:
        logger.warning("Could not upsert parent-child link: %s", e)
        summary["children_link"] = str(e)

    # 3. Seed Skill Mastery (student_skill_mastery)
    mastery_seeded = 0
    for skill_id, prob in DEMO_MASTERY_PROBS.items():
        try:
            sb.table("student_skill_mastery").upsert({
                "student_id": DEMO_STUDENT_ID,
                "skill_id": skill_id,
                "mastery_prob": prob,
                "updated_at": now.isoformat(),
            }, on_conflict="student_id,skill_id").execute()
            mastery_seeded += 1
        except Exception as e:
            logger.warning("Could not upsert mastery for %s: %s", skill_id, e)
    summary["mastery_records"] = mastery_seeded

    # 4. Seed Arcade Game Progress (student_game_progress)
    games_seeded = 0
    for game in DEMO_GAMES:
        try:
            sb.table("student_game_progress").upsert({
                **game,
                "last_played": (now - datetime.timedelta(hours=2)).isoformat(),
                "updated_at": now.isoformat(),
            }, on_conflict="student_id,game_id").execute()
            games_seeded += 1
        except Exception as e:
            logger.warning("Could not upsert game progress for %s: %s", game["game_id"], e)
    summary["game_records"] = games_seeded

    # 5. Fetch available problems from problems table to associate realistic events
    problem_map: dict[str, list[str]] = {}
    try:
        p_res = sb.table("problems").select("id, skill_id").limit(100).execute()
        for p in (p_res.data or []):
            sk = p.get("skill_id")
            if sk:
                problem_map.setdefault(sk, []).append(p["id"])
    except Exception as e:
        logger.warning("Could not fetch problem IDs: %s", e)

    # Fallback problem IDs if none returned
    def get_prob_id(skill: str) -> str | None:
        ids = problem_map.get(skill)
        if ids and len(ids) > 0:
            return ids[0]
        return None

    # 6. Seed 3 Realistic Sessions with explicit start & end times
    # Session 1: 3 hours ago (35 minutes duration)
    # Session 2: 2 days ago (40 minutes duration)
    # Session 3: 5 days ago (30 minutes duration)
    # Total duration = 105 minutes
    session_defs = [
        {
            "id": "e41ca4d1-9857-43f9-a1e5-417cda4a268c",
            "started_at": (now - datetime.timedelta(hours=3, minutes=35)).isoformat(),
            "ended_at": (now - datetime.timedelta(hours=3)).isoformat(),
            "student_id": DEMO_STUDENT_ID,
            "student_name": DEMO_STUDENT_NAME,
        },
        {
            "id": "091de6ab-6eb8-4f92-9e4d-20ade5b8ecf4",
            "started_at": (now - datetime.timedelta(days=2, hours=4, minutes=40)).isoformat(),
            "ended_at": (now - datetime.timedelta(days=2, hours=4)).isoformat(),
            "student_id": DEMO_STUDENT_ID,
            "student_name": DEMO_STUDENT_NAME,
        },
        {
            "id": "15320dad-b4e0-4a7a-97b1-2c2f6fed297c",
            "started_at": (now - datetime.timedelta(days=5, hours=6, minutes=30)).isoformat(),
            "ended_at": (now - datetime.timedelta(days=5, hours=6)).isoformat(),
            "student_id": DEMO_STUDENT_ID,
            "student_name": DEMO_STUDENT_NAME,
        },
    ]

    sessions_seeded = 0
    for s_def in session_defs:
        try:
            sb.table("sessions").upsert(s_def, on_conflict="id").execute()
            sessions_seeded += 1
        except Exception as e:
            logger.warning("Could not upsert session %s: %s", s_def["id"], e)
    summary["sessions"] = sessions_seeded

    # 7. Seed 15 Genuine Problem Attempt Events across the sessions
    # 11 Solved, 4 Attempted/Guided -> 73% genuine accuracy
    prob_3oa1 = get_prob_id("3.OA.A.1")
    prob_3oa2 = get_prob_id("3.OA.A.2")
    prob_3oa8 = get_prob_id("3.OA.D.8")
    prob_4nfa1 = get_prob_id("4.NF.A.1")
    prob_4nfb3 = get_prob_id("4.NF.B.3")

    event_specs = [
        # Session 1 (Recent - 5 problems, 4 solved, 1 guided)
        {
            "session_id": session_defs[0]["id"],
            "problem_id": prob_4nfa1,
            "attempt_text": "2/4 is the same as 1/2 because both numerator and denominator divide by 2.",
            "is_correct": True,
            "agent_response": "Spot on! Simplifying by dividing top and bottom by 2 gives the exact equivalent fraction.",
            "created_at": (now - datetime.timedelta(hours=3, minutes=30)).isoformat(),
        },
        {
            "session_id": session_defs[0]["id"],
            "problem_id": prob_4nfb3,
            "attempt_text": "1/4 + 2/4 = 3/8",
            "is_correct": False,
            "agent_response": "Look closely at the slices! If you have 1 fourth-slice and 2 more fourth-slices, how many fourth-slices do you have in all?",
            "created_at": (now - datetime.timedelta(hours=3, minutes=22)).isoformat(),
        },
        {
            "session_id": session_defs[0]["id"],
            "problem_id": prob_4nfb3,
            "attempt_text": "Oh, the denominator stays the same, so it is 3/4!",
            "is_correct": True,
            "agent_response": "Exactly right! When the denominators are equal, we only add the numerators. Excellent recovery!",
            "created_at": (now - datetime.timedelta(hours=3, minutes=18)).isoformat(),
        },
        {
            "session_id": session_defs[0]["id"],
            "problem_id": prob_3oa8,
            "attempt_text": "There are 3 packs of 4 pencils, which is 12 pencils. Then Alex gave away 5 pencils, so 12 - 5 = 7 pencils.",
            "is_correct": True,
            "agent_response": "Terrific two-step reasoning! First multiplication, then subtraction. You nailed both steps.",
            "created_at": (now - datetime.timedelta(hours=3, minutes=10)).isoformat(),
        },
        {
            "session_id": session_defs[0]["id"],
            "problem_id": prob_3oa1,
            "attempt_text": "7 groups of 8 apples is 7 x 8 = 56 apples.",
            "is_correct": True,
            "agent_response": "Perfect multiplication! 7 times 8 is 56.",
            "created_at": (now - datetime.timedelta(hours=3, minutes=2)).isoformat(),
        },

        # Session 2 (2 days ago - 6 problems, 4 solved, 2 guided)
        {
            "session_id": session_defs[1]["id"],
            "problem_id": prob_3oa2,
            "attempt_text": "24 cookies shared equally among 4 kids means 24 / 4 = 6 cookies each.",
            "is_correct": True,
            "agent_response": "Great division strategy! Each child receives 6 cookies.",
            "created_at": (now - datetime.timedelta(days=2, hours=4, minutes=35)).isoformat(),
        },
        {
            "session_id": session_defs[1]["id"],
            "problem_id": prob_3oa2,
            "attempt_text": "36 stickers divided into 6 sheets is 36 / 6 = 6 stickers per sheet.",
            "is_correct": True,
            "agent_response": "Correct! 6 groups of 6 gives 36 stickers total.",
            "created_at": (now - datetime.timedelta(days=2, hours=4, minutes=28)).isoformat(),
        },
        {
            "session_id": session_defs[1]["id"],
            "problem_id": prob_3oa8,
            "attempt_text": "Sam had $20. Bought 2 books at $6 each. Spent 2 + 6 = $8.",
            "is_correct": False,
            "agent_response": "If each book costs $6, and Sam bought 2 books, what operation finds the cost of both books together?",
            "created_at": (now - datetime.timedelta(days=2, hours=4, minutes=20)).isoformat(),
        },
        {
            "session_id": session_defs[1]["id"],
            "problem_id": prob_3oa8,
            "attempt_text": "Oh 2 times 6 is $12! And $20 - $12 = $8 left.",
            "is_correct": True,
            "agent_response": "You got it! 2 x 6 is 12, leaving 8 dollars.",
            "created_at": (now - datetime.timedelta(days=2, hours=4, minutes=15)).isoformat(),
        },
        {
            "session_id": session_defs[1]["id"],
            "problem_id": prob_4nfb3,
            "attempt_text": "5/8 - 2/8 = 3/0",
            "is_correct": False,
            "agent_response": "Notice how 8th-slices stay 8th-slices. 5 eighths minus 2 eighths leaves how many eighths?",
            "created_at": (now - datetime.timedelta(days=2, hours=4, minutes=8)).isoformat(),
        },
        {
            "session_id": session_defs[1]["id"],
            "problem_id": prob_4nfb3,
            "attempt_text": "3/8! The bottom number stays 8.",
            "is_correct": True,
            "agent_response": "Brilliant! 5 eighths minus 2 eighths is 3 eighths.",
            "created_at": (now - datetime.timedelta(days=2, hours=4, minutes=2)).isoformat(),
        },

        # Session 3 (5 days ago - 4 problems, 3 solved, 1 guided)
        {
            "session_id": session_defs[2]["id"],
            "problem_id": prob_3oa1,
            "attempt_text": "6 boxes of 8 crayons is 6 x 8 = 48 crayons.",
            "is_correct": True,
            "agent_response": "Well done! 6 times 8 equals 48.",
            "created_at": (now - datetime.timedelta(days=5, hours=6, minutes=25)).isoformat(),
        },
        {
            "session_id": session_defs[2]["id"],
            "problem_id": prob_3oa1,
            "attempt_text": "4 tables with 5 chairs each: 4 x 5 = 20 chairs.",
            "is_correct": True,
            "agent_response": "Spot on multiplication!",
            "created_at": (now - datetime.timedelta(days=5, hours=6, minutes=18)).isoformat(),
        },
        {
            "session_id": session_defs[2]["id"],
            "problem_id": prob_3oa2,
            "attempt_text": "40 markers in 5 boxes: 40 / 5 = 7 markers",
            "is_correct": False,
            "agent_response": "Close! What is 5 times 7? What is 5 times 8?",
            "created_at": (now - datetime.timedelta(days=5, hours=6, minutes=10)).isoformat(),
        },
        {
            "session_id": session_defs[2]["id"],
            "problem_id": prob_3oa2,
            "attempt_text": "5 x 8 = 40, so 40 / 5 = 8 markers per box.",
            "is_correct": True,
            "agent_response": "You figured it out! 40 divided by 5 is 8.",
            "created_at": (now - datetime.timedelta(days=5, hours=6, minutes=2)).isoformat(),
        },
    ]

    events_seeded = 0
    # Check if demo student already has these events
    try:
        existing_ev = sb.table("session_events").select("id").eq("student_id", DEMO_STUDENT_ID).execute()
        existing_count = len(existing_ev.data) if existing_ev.data else 0
        if existing_count < len(event_specs):
            for spec in event_specs:
                row_data = {
                    "id": str(uuid.uuid4()),
                    "student_id": DEMO_STUDENT_ID,
                    **spec,
                }
                sb.table("session_events").insert(row_data).execute()
                events_seeded += 1
            summary["session_events"] = f"seeded {events_seeded} new events"
        else:
            summary["session_events"] = f"already had {existing_count} events"
    except Exception as e:
        logger.warning("Could not seed session events: %s", e)
        summary["session_events"] = str(e)

    logger.info("Demo learner activity seeding complete: %s", summary)
    return summary


def ensure_demo_data_seeded() -> None:
    """
    Non-blocking check to ensure demo account has baseline data.
    Runs on server startup.
    """
    try:
        sb = get_supabase()
        res = sb.table("student_skill_mastery").select("skill_id").eq("student_id", DEMO_STUDENT_ID).execute()
        if not res.data or len(res.data) < 3:
            logger.info("Demo student has < 3 skills in mastery; initiating demo activity seed...")
            seed_demo_learner_activity()
        else:
            # Check game progress
            g_res = sb.table("student_game_progress").select("game_id").eq("student_id", DEMO_STUDENT_ID).execute()
            if not g_res.data or len(g_res.data) < 2:
                logger.info("Demo student missing game progress; initiating demo activity seed...")
                seed_demo_learner_activity()
    except Exception as e:
        logger.warning("Auto demo-seed check encountered non-fatal error: %s", e)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO)
    print("[INFO] Seeding genuine demo learner activity...")
    result = seed_demo_learner_activity()
    print("[SUCCESS] Result:", result)
