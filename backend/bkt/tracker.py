"""
Bayesian Knowledge Tracing (BKT) — pure Python implementation.
Uses standard Option-B priors from parameters.json.
Parameters per skill: prior, learn, guess, slip.
"""
import json
from pathlib import Path

# Load skill parameters at module import
_PARAMS_PATH = Path(__file__).parent / "parameters.json"
_SKILL_PARAMS: dict[str, dict] = {}
_ORDERED_SKILLS: list[dict] = []

def _load_params():
    global _SKILL_PARAMS, _ORDERED_SKILLS
    try:
        if _PARAMS_PATH.exists():
            with open(_PARAMS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _SKILL_PARAMS = {s["id"]: s for s in data.get("skills", [])}
            _ORDERED_SKILLS = sorted(_SKILL_PARAMS.values(), key=lambda s: s.get("sequence_order", 0))
    except Exception as e:
        print(f"[WARN] Failed to load BKT parameters: {e}")

_load_params()


def get_skill_params(skill_id: str) -> dict:
    """Return BKT params for a skill, falling back to defaults."""
    default = {"prior": 0.3, "learn": 0.15, "guess": 0.2, "slip": 0.1}
    return _SKILL_PARAMS.get(skill_id, default)


def get_all_skills() -> list[dict]:
    return list(_SKILL_PARAMS.values())


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
