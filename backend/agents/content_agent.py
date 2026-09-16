"""
Content Agent — RAG-based problem selection using pgvector + mastery state.
Picks the NEXT problem targeted at the student's diagnosed skill gap.
"""
# pyright: reportMissingImports=false
import os
import re
import json
import uuid
from pathlib import Path
from pydantic import SecretStr
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from db.supabase_client import get_supabase
from bkt.tracker import get_skill_params
from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION, CHAT_MODEL


# Centralized Embedding Model Configuration
EMBEDDING_MODEL_NAME: str = EMBEDDING_MODEL


def embed_text(text: str) -> list[float]:
    """Embed a text string using Gemini embedding model."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL_NAME,
        google_api_key=SecretStr(api_key),
    )
    return embeddings.embed_query(text, output_dimensionality=EMBEDDING_DIMENSION)


LOCAL_SEED_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "seed_problems.json"
_LOCAL_PROBLEMS_CACHE: list[dict] | None = None


def _load_local_problems() -> list[dict]:
    global _LOCAL_PROBLEMS_CACHE
    if _LOCAL_PROBLEMS_CACHE is not None:
        return _LOCAL_PROBLEMS_CACHE
    if not LOCAL_SEED_FILE.exists():
        return []
    try:
        with open(LOCAL_SEED_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            problems = []
            for i, p in enumerate(raw):
                item = dict(p)
                if not item.get("id"):
                    item["id"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"veritas.seed.{i+1}.{item.get('title', 'math')}"))
                problems.append(item)
            _LOCAL_PROBLEMS_CACHE = problems
            return problems
    except Exception as e:
        print(f"[WARN] Failed to load local seed problems: {e}")
        return []


def _get_local_fallback_problem(skill_id: str, exclude_ids: set[str]) -> dict | None:
    problems = _load_local_problems()
    if not problems:
        return None
    skill_matches = [p for p in problems if p.get("skill_id") == skill_id and str(p.get("id")) not in exclude_ids]
    if skill_matches:
        return skill_matches[0]
    skill_any = [p for p in problems if p.get("skill_id") == skill_id]
    if skill_any:
        return skill_any[0]
    non_excluded = [p for p in problems if str(p.get("id")) not in exclude_ids]
    if non_excluded:
        return non_excluded[0]
    return problems[0]


def _enrich_problem(prob: dict | None) -> dict | None:
    """Enrich problem dict with human-readable skill_name based on skill_id and strip dataset tags."""
    if not prob:
        return None
    p = dict(prob)
    if "title" in p and isinstance(p["title"], str):
        p["title"] = re.sub(r"^GSM8K:\s*", "", p["title"], flags=re.IGNORECASE).strip()
    s_id = p.get("skill_id", "")
    try:
        params = get_skill_params(s_id)
        p["skill_name"] = params.get("name", s_id)
    except Exception:
        p["skill_name"] = s_id
    return p


def score_candidate_adaptive(
    candidate: dict,
    target_min_diff: int,
    target_max_diff: int,
    mastery_prob: float,
    misconception_text: str | None = None,
    candidate_rank: int = 0,
) -> float:
    """
    Compute multi-factor utility score for adaptive problem selection:
    1. Semantic similarity / retrieval rank bonus (0.0 to 1.0)
    2. Difficulty fit (distance to optimal ZPD difficulty)
    3. Misconception targeting bonus (keyword matching against diagnosed error)
    4. Mastery gap urgency (1.0 - mastery_prob)
    """
    diff = candidate.get("difficulty", 1)
    target_center = (target_min_diff + target_max_diff) / 2.0
    # Difficulty fit: 1.0 if at target center, decays smoothly with distance
    diff_dist = abs(diff - target_center)
    difficulty_score = max(0.0, 1.0 - (diff_dist * 0.35))

    # Retrieval relevance bonus from pgvector rank (1st = 1.0, 2nd = 0.88, etc.)
    sim_score = max(0.2, 1.0 - (candidate_rank * 0.12))

    # Misconception match bonus
    misc_score = 0.0
    if misconception_text:
        cand_text = (
            str(candidate.get("text", "")) + " " +
            str(candidate.get("title", "")) + " " +
            str(candidate.get("expected_steps", ""))
        ).lower()
        misc_keywords = [w for w in re.findall(r"\w+", misconception_text.lower()) if len(w) > 3]
        if misc_keywords:
            matched = sum(1 for kw in misc_keywords if kw in cand_text)
            misc_score = min(1.0, matched / len(misc_keywords))

    # Mastery gap: students with lower mastery benefit more from tightly focused problems
    mastery_gap = max(0.1, 1.0 - mastery_prob)

    # Composite weighted utility: weights 0.35 sim, 0.30 difficulty fit, 0.20 misconception, 0.15 mastery gap
    total_score = (
        0.35 * sim_score +
        0.30 * difficulty_score +
        0.20 * misc_score +
        0.15 * mastery_gap
    )
    return total_score


def get_next_problem(
    skill_id: str,
    mastery_prob: float,
    student_id: str,
    exclude_problem_ids: list[str] | None = None,
    misconception_text: str | None = None,
) -> dict | None:
    """
    Retrieve the next problem from Supabase using pgvector semantic similarity search,
    calibrated to the student's diagnosed misconception and mastery level.

    Difficulty selection logic:
        mastery < 0.4  → difficulty 1-2 (build confidence)
        0.4 ≤ mastery < 0.7 → difficulty 2-3 (consolidate)
        mastery ≥ 0.7  → difficulty 3-5 (challenge)
    """
    supabase = get_supabase()
    exclude_ids = set(exclude_problem_ids or [])

    # Determine target difficulty range
    if mastery_prob < 0.4:
        min_diff, max_diff = 1, 2
    elif mastery_prob < 0.7:
        min_diff, max_diff = 2, 3
    else:
        min_diff, max_diff = 3, 5

    # ── 1. Vector Search via pgvector match_problems RPC ─────────────────────
    try:
        query_text = (
            f"Remediation problem for misconception: {misconception_text}"
            if misconception_text
            else f"Introductory practice problem for skill {skill_id} difficulty {min_diff} to {max_diff}"
        )
        query_embedding = embed_text(query_text)

        rpc_res = supabase.rpc(
            "match_problems",
            {
                "query_embedding": query_embedding,
                "skill_filter": skill_id,
                "match_count": 8,
            },
        ).execute()

        candidates = rpc_res.data or []
        # Filter out already attempted problems
        fresh_candidates = [p for p in candidates if str(p.get("id")) not in exclude_ids]

        if fresh_candidates:
            # Score each candidate adaptively via multi-factor pedagogical ranker
            scored_candidates = [
                (score_candidate_adaptive(p, min_diff, max_diff, mastery_prob, misconception_text, i), p)
                for i, p in enumerate(fresh_candidates)
            ]
            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            chosen = scored_candidates[0][1]
            return _enrich_problem(chosen)
    except Exception as e:
        print(f"[WARN] pgvector match_problems RPC skipped/failed ({e}), falling back to direct SQL query.")

    # ── 2. Fallback SQL query (filter by skill + difficulty) ──────────────────
    result_data = []
    try:
        query = (
            supabase.table("problems")
            .select("*")
            .eq("skill_id", skill_id)
            .gte("difficulty", min_diff)
            .lte("difficulty", max_diff)
        )

        if exclude_problem_ids:
            query = query.not_.in_("id", exclude_problem_ids)

        result = query.limit(5).execute()
        result_data = result.data or []

        if not result_data:
            fallback_query = supabase.table("problems").select("*").eq("skill_id", skill_id)
            if exclude_problem_ids:
                fallback_query = fallback_query.not_.in_("id", exclude_problem_ids)
            result = fallback_query.limit(3).execute()
            result_data = result.data or []

        if not result_data:
            result = supabase.table("problems").select("*").eq("skill_id", skill_id).limit(1).execute()
            result_data = result.data or []
    except Exception as sql_err:
        print(f"[WARN] Fallback SQL query error ({sql_err}), falling back to local problems.")

    # ── 3. Resilient Local Seed Problem Fallback ─────────────────────────────
    if not result_data:
        local_fallback = _get_local_fallback_problem(skill_id, exclude_ids)
        if local_fallback:
            print(f"[INFO] Using resilient local seed problem for skill {skill_id}: {local_fallback.get('title')}")
            return _enrich_problem(local_fallback)
        return None

    scored_sql = [
        (score_candidate_adaptive(p, min_diff, max_diff, mastery_prob, misconception_text, i), p)
        for i, p in enumerate(result_data)
    ]
    scored_sql.sort(key=lambda x: x[0], reverse=True)
    return _enrich_problem(scored_sql[0][1])


def generate_session_summary(
    student_name: str,
    problems_attempted: list[dict],
    mastery_state: dict[str, float],
    skill_params: list[dict],
) -> str:
    """
    Generate an LLM-written session summary for the teacher/parent dashboard.
    """
    model_name = os.environ.get("GEMINI_MODEL", CHAT_MODEL)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=0.4,
        max_output_tokens=500,
        max_retries=0,
        timeout=10,
    )

    # Build mastery summary string
    skill_lookup = {s["id"]: s["name"] for s in skill_params}
    mastery_lines = []
    for skill_id, prob in mastery_state.items():
        name = skill_lookup.get(skill_id, skill_id)
        level = "Strong" if prob >= 0.7 else ("Developing" if prob >= 0.4 else "Needs work")
        mastery_lines.append(f"  • {name}: {level} ({prob*100:.0f}%)")

    # Summarize attempts
    attempts_lines = []
    for p in problems_attempted[-5:]:  # last 5 problems
        status = "Correct" if p.get("is_correct") else f"Incorrect ({p.get('misconception_type', 'incorrect')})"
        attempts_lines.append(f"  • {p.get('problem_title', 'Problem')}: {status}")

    prompt = f"""Write a warm, professional 3-paragraph session summary for a parent or teacher about {student_name}'s tutoring session.

SKILL MASTERY:
{chr(10).join(mastery_lines)}

PROBLEMS ATTEMPTED:
{chr(10).join(attempts_lines)}

Paragraph 1: What the student worked on today and their overall engagement.
Paragraph 2: Specific strengths observed and any misconceptions identified (be specific, not generic).
Paragraph 3: Recommended next steps for the student and one encouragement note for the parent.

Keep it under 150 words total. Warm, specific, actionable."""

    messages = [
        SystemMessage(content="You are an expert education data analyst writing parent-facing session reports."),
        HumanMessage(content=prompt),
    ]
    try:
        response = llm.invoke(messages)
        return str(response.content).strip()
    except Exception as e:
        print(f"[WARN] Failed to generate LLM summary: {e}")
        return f"{student_name} completed an active practice session today. The tutor tracked student engagement across core math concepts. Continued practice with targeted guidance is recommended to solidify problem-solving fluency."
