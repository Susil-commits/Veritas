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
from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION, CHAT_MODEL, CHAT_MODEL_CASCADE, extract_clean_text


# Centralized Embedding Model Configuration
EMBEDDING_MODEL_NAME: str = EMBEDDING_MODEL


# In-memory LRU-style embedding cache to prevent rate-limit spikes (e.g. 100 RPM quota)
_EMBEDDING_CACHE: dict[str, list[float]] = {}


import hashlib

def _deterministic_mock_embedding(text: str, dim: int = EMBEDDING_DIMENSION) -> list[float]:
    """
    Generate a deterministic, zero-cost 768-dim pseudo-vector from text hash.
    Consumes 0 Gemini API credits during tests and provides seamless quota resilience.
    """
    seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
    state = int.from_bytes(seed_bytes[:8], "big")
    vec: list[float] = []
    for _ in range(dim):
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        norm_val = round(((state / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0), 6)
        vec.append(norm_val)
    return vec


def embed_text(text: str) -> list[float]:
    """Embed a text string using Gemini embedding model with caching and zero-credit test bypass."""
    cached = _EMBEDDING_CACHE.get(text)
    if cached is not None:
        return cached

    # Zero-credit test mode bypass (used by automated test suites)
    if os.environ.get("VERITAS_TEST_MODE") == "true" or os.environ.get("VERITAS_MOCK_LLM") == "true":
        res = _deterministic_mock_embedding(text)
        _EMBEDDING_CACHE[text] = res
        return res

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        res = _deterministic_mock_embedding(text)
        _EMBEDDING_CACHE[text] = res
        return res

    try:
        embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL_NAME,
            google_api_key=SecretStr(api_key),
        )
        res = embeddings.embed_query(text, output_dimensionality=EMBEDDING_DIMENSION)
    except Exception as e:
        print(f"[WARN] Gemini embedding API call failed ({e}); using zero-credit deterministic vector.")
        res = _deterministic_mock_embedding(text)

    # Cache up to 200 distinct problem query vectors in memory
    if len(_EMBEDDING_CACHE) > 200:
        _EMBEDDING_CACHE.pop(next(iter(_EMBEDDING_CACHE)))
    _EMBEDDING_CACHE[text] = res
    return res


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


def extract_math_tokens(text: str) -> set[str]:
    """Extract salient mathematical and conceptual tokens, excluding common stopwords."""
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "what", "how",
        "student", "problem", "calculate", "solve", "remediation", "misconception",
        "introductory", "practice", "difficulty", "skill", "instead", "after",
        "evaluated", "forgot", "resulted", "larger", "quantity", "operation",
        "stopped", "evaluation", "evaluates", "find", "show", "each", "step",
        "when", "where", "which", "into", "their", "your", "does", "been", "was"
    }
    clean = re.sub(r"[_\W]+", " ", text.lower())
    return {w for w in clean.split() if len(w) >= 2 and w not in stop_words}


def compute_lexical_similarity(
    query_text: str | None,
    candidate: dict,
    keywords: list[str] | None = None,
) -> float:
    """
    Compute lexical token overlap / Jaccard similarity when vector embedding
    similarity is not available (e.g. local fallback or offline execution).
    """
    q_tokens = set()
    if keywords:
        q_tokens.update(kw.lower() for kw in keywords)
    if query_text:
        q_tokens.update(extract_math_tokens(query_text))
    if not q_tokens:
        return 0.0

    steps = candidate.get("expected_steps") or []
    steps_str = " ".join(steps) if isinstance(steps, list) else str(steps)
    cand_text = f"{candidate.get('title', '')} {candidate.get('text', '')} {steps_str}".lower()
    c_tokens = extract_math_tokens(cand_text)
    if not c_tokens:
        return 0.0

    overlap = len(q_tokens & c_tokens)
    recall = overlap / len(q_tokens)
    jaccard = overlap / len(q_tokens | c_tokens)
    # Blend: 70% query coverage + 30% Jaccard
    score = 0.7 * recall + 0.3 * jaccard
    return max(0.0, min(1.0, score))


def score_candidate_adaptive(
    candidate: dict,
    target_min_diff: int,
    target_max_diff: int,
    mastery_prob: float,
    misconception_text: str | None = None,
    candidate_rank: int = 0,
    query_text: str | None = None,
    keywords: list[str] | None = None,
) -> float:
    """
    Compute multi-factor utility score for adaptive problem selection:
    1. Semantic similarity / retrieval rank bonus (0.0 to 1.0)
       - pgvector cosine similarity if present
       - lexical token overlap proxy when similarity is 0.0 / absent (fallback resilience)
    2. Difficulty fit (distance to optimal ZPD difficulty window)
    3. Misconception targeting bonus (exact misconception_type or keyword matching)
    4. Mastery-derived pedagogical difficulty target (heuristic mapping: d*(P(L)) = 1.0 + 4.0 * mastery_prob)
    """
    diff = candidate.get("difficulty", 1)
    target_center = (target_min_diff + target_max_diff) / 2.0
    # Difficulty fit: 1.0 if at target center, decays smoothly with distance
    diff_dist = abs(diff - target_center)
    difficulty_score = max(0.0, 1.0 - (diff_dist * 0.35))

    # Retrieval relevance: pgvector cosine similarity, with lexical similarity proxy fallback
    raw_sim = candidate.get("similarity")
    if raw_sim is not None and float(raw_sim) > 0.0:
        sim_score = max(0.0, min(1.0, float(raw_sim)))
    else:
        # Transparent lexical proxy fallback when vector similarity is unavailable
        lookup_query = query_text or misconception_text or ""
        sim_score = compute_lexical_similarity(lookup_query, candidate, keywords=keywords)

    # Misconception match bonus: exact misconception_type matching with keyword fallback
    misc_score = 0.0
    diagnosed_misconception = None
    if misconception_text:
        diagnosed_misconception = misconception_text.split(":")[0].strip().lower()

    if candidate.get("misconception_type") and diagnosed_misconception:
        misc_score = 1.0 if str(candidate.get("misconception_type")).lower() == diagnosed_misconception else 0.0
    elif keywords:
        cand_text = (
            str(candidate.get("text", "")) + " " +
            str(candidate.get("title", "")) + " " +
            str(candidate.get("expected_steps", ""))
        ).lower()
        matched = sum(1 for kw in keywords if kw.lower() in cand_text)
        misc_score = min(1.0, matched / len(keywords))
    elif misconception_text:
        cand_text = (
            str(candidate.get("text", "")) + " " +
            str(candidate.get("title", "")) + " " +
            str(candidate.get("expected_steps", ""))
        ).lower()
        misc_tokens = extract_math_tokens(misconception_text)
        if misc_tokens:
            matched = sum(1 for kw in misc_tokens if kw in cand_text)
            misc_score = min(1.0, matched / len(misc_tokens))

    # Mastery-derived pedagogical difficulty target (heuristic function):
    # Maps student mastery [0.0, 1.0] onto pedagogical difficulty scale [1.0, 5.0].
    # Low-mastery students are matched to foundational problems (avoid cognitive overload);
    # high-mastery students are matched to challenging problems (avoid boredom).
    target_continuous_diff = 1.0 + (mastery_prob * 4.0)
    mastery_alignment = max(0.0, 1.0 - (abs(diff - target_continuous_diff) / 3.0))

    # Composite weighted utility: 0.35 semantic/lexical sim, 0.25 misconception, 0.20 ZPD fit, 0.20 mastery alignment
    total_score = (
        0.35 * sim_score +
        0.25 * misc_score +
        0.20 * difficulty_score +
        0.20 * mastery_alignment
    )
    return total_score


def get_candidate_problems(
    skill_id: str | None = None,
    mastery_prob: float = 0.5,
    student_id: str = "default",
    exclude_problem_ids: list[str] | None = None,
    misconception_text: str | None = None,
    top_k: int = 5,
    unrestricted: bool = False,
    keywords: list[str] | None = None,
) -> list[dict]:
    """
    Retrieve an ordered list of candidate problems ranked by multi-factor pedagogical utility,
    calibrated to the student's diagnosed misconception, mastery level, and ZPD difficulty.

    If `unrestricted` is True or `skill_id` is None, candidates are retrieved across the entire
    curriculum problem bank rather than pre-filtered to a single skill standard.

    Difficulty selection logic:
        mastery < 0.4       → difficulty 1-2 (build confidence)
        0.4 ≤ mastery < 0.7 → difficulty 2-3 (consolidate)
        mastery ≥ 0.7       → difficulty 3-5 (challenge)
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

    effective_skill_filter = None if (unrestricted or not skill_id) else skill_id
    query_text = (
        f"Remediation problem for misconception: {misconception_text}"
        if misconception_text
        else (f"Introductory practice problem for skill {skill_id} difficulty {min_diff} to {max_diff}" if skill_id else f"Practice math problem difficulty {min_diff} to {max_diff}")
    )

    # ── 1. Vector Search via pgvector match_problems RPC ─────────────────────
    try:
        query_embedding = embed_text(query_text)

        rpc_res = supabase.rpc(
            "match_problems",
            {
                "query_embedding": query_embedding,
                "skill_filter": effective_skill_filter,
                "match_count": max(12, top_k * 3),
            },
        ).execute()

        candidates = rpc_res.data or []
        fresh_candidates = [p for p in candidates if str(p.get("id")) not in exclude_ids]

        if fresh_candidates:
            scored_candidates = [
                (score_candidate_adaptive(p, min_diff, max_diff, mastery_prob, misconception_text, i, query_text=query_text, keywords=keywords), p)
                for i, p in enumerate(fresh_candidates)
            ]
            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            enriched = [_enrich_problem(p) for _, p in scored_candidates[:top_k]]
            return [p for p in enriched if p is not None]
    except Exception as e:
        print(f"[WARN] pgvector match_problems RPC skipped/failed ({e}), falling back to direct SQL query.")

    # ── 2. Fallback Candidate Retrieval ──────────────────────────────────────
    # If unrestricted, evaluate candidate ranking across the complete curriculum problem bank.
    # If skill-restricted, query Supabase problems filtered by skill_id with local fallback.
    if unrestricted or not effective_skill_filter:
        problems = _load_local_problems()
        local_candidates = [p for p in problems if str(p.get("id")) not in exclude_ids] or problems
        scored_local = [
            (score_candidate_adaptive(p, min_diff, max_diff, mastery_prob, misconception_text, i, query_text=query_text, keywords=keywords), p)
            for i, p in enumerate(local_candidates)
        ]
        scored_local.sort(key=lambda x: x[0], reverse=True)
        enriched = [_enrich_problem(p) for _, p in scored_local[:top_k]]
        return [p for p in enriched if p is not None]

    # Skill-restricted SQL query
    result_data = []
    try:
        query = (
            supabase.table("problems")
            .select("*")
            .eq("skill_id", effective_skill_filter)
            .gte("difficulty", min_diff)
            .lte("difficulty", max_diff)
        )
        if exclude_problem_ids:
            query = query.not_.in_("id", exclude_problem_ids)

        result = query.limit(max(12, top_k * 3)).execute()
        result_data = result.data or []

        if len(result_data) < top_k:
            fallback_query = supabase.table("problems").select("*").eq("skill_id", effective_skill_filter)
            if exclude_problem_ids:
                fallback_query = fallback_query.not_.in_("id", exclude_problem_ids)
            result = fallback_query.limit(max(12, top_k * 3)).execute()
            existing_ids = {str(p.get("id")) for p in result_data}
            for p in (result.data or []):
                if str(p.get("id")) not in existing_ids:
                    result_data.append(p)
                    existing_ids.add(str(p.get("id")))

        if not result_data:
            q_all = supabase.table("problems").select("*").eq("skill_id", effective_skill_filter)
            result = q_all.limit(top_k * 2).execute()
            result_data = result.data or []
    except Exception as sql_err:
        print(f"[WARN] Fallback SQL query error ({sql_err}), falling back to local problems.")

    if result_data:
        scored_sql = [
            (score_candidate_adaptive(p, min_diff, max_diff, mastery_prob, misconception_text, i, query_text=query_text, keywords=keywords), p)
            for i, p in enumerate(result_data)
        ]
        scored_sql.sort(key=lambda x: x[0], reverse=True)
        enriched = [_enrich_problem(p) for _, p in scored_sql[:top_k]]
        return [p for p in enriched if p is not None]

    # Resilient Local Seed Problem Fallback for skill_id
    problems = _load_local_problems()
    local_candidates = [p for p in problems if p.get("skill_id") == effective_skill_filter and str(p.get("id")) not in exclude_ids]
    if not local_candidates:
        local_candidates = [p for p in problems if p.get("skill_id") == effective_skill_filter]
    if not local_candidates:
        local_candidates = problems

    scored_local = [
        (score_candidate_adaptive(p, min_diff, max_diff, mastery_prob, misconception_text, i, query_text=query_text, keywords=keywords), p)
        for i, p in enumerate(local_candidates)
    ]
    scored_local.sort(key=lambda x: x[0], reverse=True)
    enriched = [_enrich_problem(p) for _, p in scored_local[:top_k]]
    return [p for p in enriched if p is not None]


def get_next_problem(
    skill_id: str,
    mastery_prob: float,
    student_id: str,
    exclude_problem_ids: list[str] | None = None,
    misconception_text: str | None = None,
) -> dict | None:
    """
    Retrieve the single best next problem from Supabase / problem bank,
    calibrated to the student's diagnosed misconception and mastery level.
    """
    candidates = get_candidate_problems(
        skill_id=skill_id,
        mastery_prob=mastery_prob,
        student_id=student_id,
        exclude_problem_ids=exclude_problem_ids,
        misconception_text=misconception_text,
        top_k=1,
    )
    return candidates[0] if candidates else None



def generate_session_summary(
    student_name: str,
    problems_attempted: list[dict],
    mastery_state: dict[str, float],
    skill_params: list[dict],
) -> str:
    """
    Generate an LLM-written session summary for the teacher/parent dashboard.
    """
    # Zero-credit test mode bypass (used by automated test suites)
    if os.environ.get("VERITAS_TEST_MODE") == "true" or os.environ.get("VERITAS_MOCK_LLM") == "true":
        return (
            f"{student_name} completed an active math practice session today, demonstrating positive "
            f"engagement with core concepts. Analysis showed solid retention of foundation skills, with "
            f"targeted guidance addressing key step-by-step problem areas. Continued practice on related "
            f"topics is recommended to solidify fluency and boost long-term confidence."
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

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    seen = set()
    models_to_try = [m for m in CHAT_MODEL_CASCADE if m and not (m in seen or seen.add(m))]

    for m_name in models_to_try:
        try:
            llm = ChatGoogleGenerativeAI(
                model=m_name,
                google_api_key=api_key,
                max_output_tokens=500,
                max_retries=0,
                timeout=10,
            )
            response = llm.invoke(messages)
            text = extract_clean_text(response.content)
            if text:
                return text
        except Exception as e:
            print(f"[WARN] Failed to generate LLM summary on '{m_name}': {e}")

    return f"{student_name} completed an active practice session today. The tutor tracked student engagement across core math concepts. Continued practice with targeted guidance is recommended to solidify problem-solving fluency."
