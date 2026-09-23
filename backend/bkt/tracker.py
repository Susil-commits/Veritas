"""
Bayesian Knowledge Tracing (BKT) — pure Python implementation.
Uses standard Option-B priors from parameters.json.
Parameters per skill: prior, learn, guess, slip.
"""
import json
from pathlib import Path

import time
import math

# Load skill parameters: PostgreSQL Database-First with local seed fallback
_PARAMS_PATH = Path(__file__).parent / "parameters.json"
_SKILL_PARAMS: dict[str, dict] = {}
_ORDERED_SKILLS: list[dict] = []
_db_synced: bool = False
_last_sync_attempt: float = 0.0
_SYNC_COOLDOWN_SECONDS: float = 60.0


def _load_params_from_seed() -> None:
    """Load baseline seed parameters from local configuration file (cold-boot / offline fallback)."""
    global _SKILL_PARAMS, _ORDERED_SKILLS
    try:
        if _PARAMS_PATH.exists():
            with open(_PARAMS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _SKILL_PARAMS = {s["id"]: s for s in data.get("skills", [])}
            _ORDERED_SKILLS = sorted(_SKILL_PARAMS.values(), key=lambda s: s.get("sequence_order", 0))
    except Exception as e:
        print(f"[WARN] Failed to load baseline BKT parameters from seed: {e}")


def sync_skills_from_db(force: bool = False) -> bool:
    """
    Authoritative Database Synchronization.
    Fetches the live Common Core curriculum taxonomy, BKT hyperparameters, and Cognitive DAG
    directly from the PostgreSQL `skills` table, ensuring runtime curriculum modifications
    do not require code redeployment.
    """
    global _SKILL_PARAMS, _ORDERED_SKILLS, _db_synced, _last_sync_attempt
    now = time.time()
    if not force and _db_synced:
        return True
    if not force and (now - _last_sync_attempt < _SYNC_COOLDOWN_SECONDS):
        return _db_synced

    _last_sync_attempt = now
    try:
        from db.supabase_client import get_supabase
        supabase = get_supabase()
        res = supabase.table("skills").select("*").order("sequence_order").execute()
        if res.data and len(res.data) > 0:
            db_skills = {}
            for row in res.data:
                sid = row["id"]
                seed_skill = _SKILL_PARAMS.get(sid, {})
                prereqs = row.get("prerequisites")
                if prereqs is None or (isinstance(prereqs, list) and len(prereqs) == 0 and seed_skill.get("prerequisites")):
                    prereqs = seed_skill.get("prerequisites", [])

                prior = row.get("prior")
                prior_val = float(prior) if prior is not None else float(seed_skill.get("prior", 0.3))

                learn = row.get("learn")
                learn_val = float(learn) if learn is not None else float(seed_skill.get("learn", 0.15))

                guess = row.get("guess")
                guess_val = float(guess) if guess is not None else float(seed_skill.get("guess", 0.2))

                slip = row.get("slip")
                slip_val = float(slip) if slip is not None else float(seed_skill.get("slip", 0.1))

                decay = row.get("decay_rate")
                decay_val = float(decay) if decay is not None else float(seed_skill.get("decay_rate", 0.0385))

                half_life = row.get("retention_half_life_days")
                half_life_val = float(half_life) if half_life is not None else float(seed_skill.get("retention_half_life_days", 21.0))

                calibrated = row.get("calibrated")
                calibrated_val = bool(calibrated) if calibrated is not None else bool(seed_skill.get("calibrated", False))

                source = row.get("calibration_source") or seed_skill.get("source", "PostgreSQL Authoritative Database")

                db_skills[sid] = {
                    "id": sid,
                    "name": row.get("name", seed_skill.get("name", sid)),
                    "sequence_order": int(row.get("sequence_order", seed_skill.get("sequence_order", 0))),
                    "prior": prior_val,
                    "learn": learn_val,
                    "guess": guess_val,
                    "slip": slip_val,
                    "prerequisites": list(prereqs),
                    "retention_half_life_days": half_life_val,
                    "decay_rate": decay_val,
                    "calibrated": calibrated_val,
                    "source": source,
                }
            _SKILL_PARAMS = db_skills
            _ORDERED_SKILLS = sorted(_SKILL_PARAMS.values(), key=lambda s: s.get("sequence_order", 0))
            _db_synced = True
            return True
    except Exception:
        # Graceful fallback to cached seed parameters if database is unreachable / offline test mode
        pass
    return False


# Cold-boot initialization from local seed
_load_params_from_seed()


def get_skill_params(skill_id: str) -> dict:
    """Return BKT params for a skill, authoritative from DB with fallback."""
    if not _db_synced:
        sync_skills_from_db()
    default = {"prior": 0.3, "learn": 0.15, "guess": 0.2, "slip": 0.1, "prerequisites": [], "decay_rate": 0.0385}
    return _SKILL_PARAMS.get(skill_id, default)


def get_all_skills() -> list[dict]:
    """Return all skills ordered by sequence_order."""
    if not _db_synced:
        sync_skills_from_db()
    return list(_SKILL_PARAMS.values())


def get_skill_prerequisites(skill_id: str) -> list[str]:
    """Return list of prerequisite skill IDs for the given skill."""
    params = get_skill_params(skill_id)
    return list(params.get("prerequisites", []))


def get_prerequisite_graph() -> dict[str, list[str]]:
    """Return full Directed Acyclic Graph (DAG) mapping each skill to its prerequisite skills."""
    if not _db_synced:
        sync_skills_from_db()
    return {s["id"]: list(s.get("prerequisites", [])) for s in _ORDERED_SKILLS}


def apply_time_decay(
    current_mastery: float,
    elapsed_days: float,
    skill_id: str,
) -> float:
    """
    Ebbinghaus Exponential Forgetting Curve Model.
    As elapsed time dt increases, latent skill mastery asymptotically regresses
    toward the baseline cognitive prior P_prior rather than collapsing to zero:

        P(L_{t+dt}) = P_prior + (P(L_t) - P_prior) * exp(-lambda * dt)

    Given:
        current_mastery = P(L_t)
        elapsed_days    = dt (elapsed days since last session)
        lambda          = decay_rate (derived from skill retention half-life)
    """
    if elapsed_days <= 0:
        return current_mastery

    params = get_skill_params(skill_id)
    p_prior = float(params.get("prior", 0.3))
    decay_rate = float(params.get("decay_rate", 0.0385))

    if current_mastery <= p_prior:
        return current_mastery

    decayed = p_prior + (current_mastery - p_prior) * math.exp(-decay_rate * elapsed_days)
    return round(min(max(decayed, p_prior), 1.0), 4)


def diagnose_root_skill_deficit(
    mastery_state: dict[str, float],
    failing_skill_id: str,
    mastery_threshold: float = 0.65,
) -> str | None:
    """
    Traverse the prerequisite DAG backward from a failing skill to identify
    if an underlying prerequisite is unmastered (< threshold).
    Returns the deepest unmastered prerequisite skill ID, or None if all prerequisites are sound.
    """
    visited = set()
    queue = list(get_skill_prerequisites(failing_skill_id))
    unmastered_roots = []

    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)

        curr_mastery = mastery_state.get(curr, get_skill_params(curr).get("prior", 0.3))
        if curr_mastery < mastery_threshold:
            unmastered_roots.append((curr, curr_mastery))
            # Continue checking if this root itself has deeper unmastered prerequisites
            queue.extend(get_skill_prerequisites(curr))

    if unmastered_roots:
        # Return the prerequisite with the lowest mastery score
        unmastered_roots.sort(key=lambda x: x[1])
        return unmastered_roots[0][0]

    return None


VALID_ATTEMPT_TYPES = {
    "independent_attempt",
    "corrected_after_feedback",
    "hinted_attempt",
}


def update_mastery(
    current_mastery: float,
    is_correct: bool,
    skill_id: str,
    attempt_type: str = "independent_attempt",
) -> float:
    """
    BKT update equation with pedagogical attempt-type differentiation.

    Given:
        P(L_t)   = current_mastery (probability student knows the skill)
        P(T)     = learn rate
        P(G)     = guess rate (P(correct | not knowing))
        P(S)     = slip rate  (P(incorrect | knowing))
        attempt_type = 'independent_attempt' | 'corrected_after_feedback' | 'hinted_attempt'

    Pedagogical semantics:
    - independent_attempt: Full Bayesian update reflecting independent recall/synthesis.
    - corrected_after_feedback: Student corrected their response after tutor Socratic feedback.
      Learning transition applies, but positive likelihood is tempered to reflect assisted mastery.
    - hinted_attempt: Student used an explicit hint prior to answering.
      Moderate learning progress without credit for unassisted discovery.

    Returns:
        P(L_{t+1}) — updated mastery probability
    """
    params = get_skill_params(skill_id)
    p_l = current_mastery
    p_t = params["learn"]
    p_g = params["guess"]
    p_s = params["slip"]

    if is_correct:
        # P(L | correct) via Bayes
        p_correct_knowing    = 1 - p_s
        p_correct_not_knowing = p_g
        p_correct = p_l * p_correct_knowing + (1 - p_l) * p_correct_not_knowing
        p_l_given_obs = (p_l * p_correct_knowing) / p_correct if p_correct > 0 else p_l

        # Pedagogical discount for assisted vs unassisted mastery
        if attempt_type == "corrected_after_feedback":
            # Scaffolding assisted the answer: blend 50% posterior jump + learning transition
            p_l_given_obs = p_l + 0.50 * (p_l_given_obs - p_l)
        elif attempt_type == "hinted_attempt":
            # Explicit hint assisted the answer: blend 60% posterior jump
            p_l_given_obs = p_l + 0.60 * (p_l_given_obs - p_l)
    else:
        # P(L | incorrect) via Bayes
        p_wrong_knowing    = p_s
        p_wrong_not_knowing = 1 - p_g
        p_wrong = p_l * p_wrong_knowing + (1 - p_l) * p_wrong_not_knowing
        p_l_given_obs = (p_l * p_wrong_knowing) / p_wrong if p_wrong > 0 else p_l

    # Apply learning: P(L_{t+1}) = P(L|obs) + (1 - P(L|obs)) * P(T)
    p_l_next = p_l_given_obs + (1 - p_l_given_obs) * p_t

    return round(min(max(p_l_next, 0.0), 1.0), 4)


def get_next_skill(mastery_state: dict[str, float]) -> str:
    """
    Pick the next skill to practice.
    Strategy: lowest-mastery skill that is not yet mastered (< 0.85),
    respecting the curriculum sequence order.
    Falls back to the first skill if all are mastered.
    """
    if not _ORDERED_SKILLS:
        return "3.OA.A.1"

    for skill in _ORDERED_SKILLS:
        skill_id = skill["id"]
        mastery = mastery_state.get(skill_id)
        if mastery is None:
            mastery = float(skill.get("prior", 0.3))
        if mastery < 0.85:
            return skill_id

    # All mastered — loop back to most advanced skill
    return _ORDERED_SKILLS[-1]["id"]


def initialize_mastery() -> dict[str, float]:
    """Return a fresh mastery state using each skill's prior probability."""
    if not _SKILL_PARAMS:
        return {"3.OA.A.1": 0.3}
    return {
        skill_id: float(params.get("prior", 0.3))
        for skill_id, params in _SKILL_PARAMS.items()
    }
