"""
Deterministic Objective Math Evaluator.
Extracts student answers and expected solutions to verify correctness mathematically
(arithmetic, fractions, equations, expressions) before crediting BKT mastery.
"""
from fractions import Fraction
import re
from typing import Any, Tuple


def parse_fraction_or_num(raw: str) -> Fraction | None:
    """Parse integer, decimal, mixed fraction, or simple fraction into a Fraction object."""
    s = raw.strip()
    # Mixed fraction e.g. "1 1/2" or "2 3/4"
    m_mixed = re.match(r"^(\d+)\s+(\d+)/(\d+)$", s)
    if m_mixed:
        try:
            whole = int(m_mixed.group(1))
            num = int(m_mixed.group(2))
            den = int(m_mixed.group(3))
            if den == 0:
                return None
            return Fraction(whole * den + num, den)
        except Exception:
            return None

    # Simple fraction e.g. "3/4" or "-5/8"
    m_frac = re.match(r"^(-?\d+)/(\d+)$", s)
    if m_frac:
        try:
            num = int(m_frac.group(1))
            den = int(m_frac.group(2))
            if den == 0:
                return None
            return Fraction(num, den)
        except Exception:
            return None

    # Float or integer e.g. "40", "0.75", "-12"
    try:
        val = float(s)
        return Fraction(val).limit_denominator(10000)
    except Exception:
        return None


def extract_expected_answer(problem: dict) -> Tuple[str | None, str]:
    """
    Extract the canonical expected answer and its type from problem dict.
    Returns (canonical_str, answer_type: 'equation' | 'fraction' | 'number' | 'expression' | 'none')
    """
    # 1. Check explicit answer attribute
    explicit_ans = problem.get("answer")
    if explicit_ans is not None and str(explicit_ans).strip():
        ans_str = str(explicit_ans).strip()
    else:
        # 2. Extract from expected_steps[-1]
        steps = problem.get("expected_steps") or []
        if not steps:
            return None, "none"
        last_step = str(steps[-1]).strip()
        ans_match = re.search(r"Answer:\s*(.*)", last_step, re.IGNORECASE)
        ans_str = ans_match.group(1).strip() if ans_match else last_step

    # Check for equation e.g. "x = 4"
    eq_match = re.search(r"\b([a-zA-Z])\s*=\s*(-?\d+(?:/\d+)?(?:\.\d+)?)\b", ans_str)
    if eq_match:
        return f"{eq_match.group(1).lower()} = {eq_match.group(2)}", "equation"

    # Check for mixed fraction e.g. "1 1/2"
    mixed_match = re.search(r"\b(\d+\s+\d+/\d+)\b", ans_str)
    if mixed_match:
        return mixed_match.group(1), "fraction"

    # Check for simple fraction e.g. "3/4"
    frac_match = re.search(r"\b(-?\d+/\d+)\b", ans_str)
    if frac_match:
        return frac_match.group(1), "fraction"

    # Check for multi-term algebraic expression e.g. "2p + h", "h + 2p", "2p - h", "15 + 4t", "n + 7"
    multi_expr = re.search(r"\b((?:[0-9]*[a-zA-Z]|[0-9]+(?:\.[0-9]+)?)(?:\s*[+\-*/]\s*(?:[0-9]*[a-zA-Z]|[0-9]+(?:\.[0-9]+)?))+)\b", ans_str)
    if multi_expr and re.search(r"[a-zA-Z]", multi_expr.group(1)):
        return multi_expr.group(1), "expression"

    # Check for single variable expression e.g. "9w", "2p", "4a"
    single_term = re.search(r"\b([0-9]+[a-zA-Z])\b", ans_str)
    if single_term:
        return single_term.group(1), "expression"
    if re.match(r"^[a-zA-Z]$", ans_str.strip()):
        return ans_str.strip(), "expression"

    # Check for clean number e.g. "40", "16", "41.5"
    num_match = re.search(r"\b(-?\d+(?:\.\d+)?)\b", ans_str)
    if num_match:
        return num_match.group(1), "number"

    return ans_str, "expression"


def extract_student_candidate(message: str) -> list[Tuple[str, str]]:
    """
    Extract candidate answers from student's message with their identified types.
    Ensures candidates are anchored to answer intent, rejecting negated values,
    disjunctive alternative queries (e.g. 'is it 12 or 15?'), and arbitrary
    contextual numbers in long conversational sentences.
    Returns list of (candidate_str, candidate_type).
    """
    text = message.strip()
    if not text:
        return []

    # 1. Disjunctive alternative questions (e.g. "Is the answer 12 or 15?", "is it 3/4 or 5/8?")
    # These represent undecided student inquiries rather than definite answer commitments.
    if re.search(r"\b(?:is\s+it|is\s+the\s+answer|could\s+it\s+be|what\s+about)\b.+\b\d+\b.+\bor\b.+\b\d+\b", text, flags=re.IGNORECASE) or \
       re.search(r"\b\d+(?:/\d+)?(?:\.\d+)?\s+or\s+\d+(?:/\d+)?(?:\.\d+)?\b", text, flags=re.IGNORECASE):
        return []

    words = text.split()
    is_short_direct = len(words) <= 5

    candidates: list[Tuple[str, str]] = []
    seen = set()

    def add_cand(val: str, c_type: str):
        v = val.strip()
        if v and (v.lower(), c_type) not in seen:
            seen.add((v.lower(), c_type))
            candidates.append((v, c_type))

    # Identify all negated numbers and spans (e.g., "isn't 12", "not 12", "not equal to 12")
    negated_spans = []
    negated_numbers = set()
    for neg_match in re.finditer(r"\b(?:isn't|is\s+not|not|wasn't|cannot\s+be|can't\s+be|not\s+equal\s+to)\s*(-?\d+(?:/\d+)?(?:\.\d+)?)", text, flags=re.IGNORECASE):
        negated_spans.append(neg_match.span(1))
        negated_numbers.add(neg_match.group(1).strip())

    def is_in_negation(start: int, end: int, val: str = "") -> bool:
        if val and val in negated_numbers:
            return True
        return any(ns <= start and end <= ne for ns, ne in negated_spans)

    # 1. Check explicit variable equations e.g. "x = 4", "a = 1/2"
    has_equation = False
    for eq in re.finditer(r"\b([a-zA-Z])\s*=\s*(-?\d+(?:/\d+)?(?:\.\d+)?)\b", text):
        eq_val = eq.group(2).strip()
        if not is_in_negation(eq.start(2), eq.end(2), eq_val):
            has_equation = True
            add_cand(f"{eq.group(1).lower()} = {eq.group(2)}", "equation")

    # 2. Extract candidates anchored to explicit answer-intent phrases (if not an equation)
    if not has_equation:
        intent_patterns = [
            r"(?:the\s+)?answer\s*(?:is|should\s+be|=|:)\s*(-?\d+\s+\d+/\d+|-?\d+/\d+|-?\d+(?:\.\d+)?|(?:[0-9]*[a-zA-Z]|[0-9]+)(?:\s*[+\-*/]\s*(?:[0-9]*[a-zA-Z]|[0-9]+))+)",
            r"(?:i\s+got|i\s+get|i\s+found|my\s+answer\s+is)\s*(-?\d+\s+\d+/\d+|-?\d+/\d+|-?\d+(?:\.\d+)?|(?:[0-9]*[a-zA-Z]|[0-9]+)(?:\s*[+\-*/]\s*(?:[0-9]*[a-zA-Z]|[0-9]+))+)",
            r"(?:i\s+think\s+(?:the\s+answer\s+is|it(?:'s|s|\s+is))\s*|maybe\s+it(?:'s|s|\s+is)\s*|maybe\s+)\s*(-?\d+\s+\d+/\d+|-?\d+/\d+|-?\d+(?:\.\d+)?|(?:[0-9]*[a-zA-Z]|[0-9]+)(?:\s*[+\-*/]\s*(?:[0-9]*[a-zA-Z]|[0-9]+))+)",
            r"(?:so|therefore|equals?)\s+(-?\d+\s+\d+/\d+|-?\d+/\d+|-?\d+(?:\.\d+)?)",
            r"(?:is\s+it|is\s+the\s+simplified\s+fraction|decimal\s+form\s+is)\s*(-?\d+\s+\d+/\d+|-?\d+/\d+|-?\d+(?:\.\d+)?)",
        ]

        for pat in intent_patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                c_val = m.group(1).strip()
                if not is_in_negation(m.start(1), m.end(1), c_val):
                    if "/" in c_val and " " in c_val:
                        add_cand(c_val, "fraction")
                    elif "/" in c_val:
                        add_cand(c_val, "fraction")
                    elif re.match(r"^-?\d+(?:\.\d+)?$", c_val):
                        add_cand(c_val, "number")
                    else:
                        add_cand(c_val, "expression")

    # 3. For short/direct messages (<= 5 words), extract bare fractions, numbers, or expressions
    if is_short_direct and not candidates:
        # Mixed fractions e.g. "1 1/2"
        for mf in re.finditer(r"\b(\d+\s+\d+/\d+)\b", text):
            if not is_in_negation(mf.start(1), mf.end(1), mf.group(1).strip()):
                add_cand(mf.group(1), "fraction")

        # Simple fractions e.g. "3/4", "6/8"
        for sf in re.finditer(r"\b(-?\d+/\d+)\b", text):
            if not is_in_negation(sf.start(1), sf.end(1), sf.group(1).strip()):
                add_cand(sf.group(1), "fraction")

        # Expressions e.g. "2p + h", "h + 2p", "15 + 4t"
        for ex in re.finditer(r"\b((?:[0-9]*[a-zA-Z]|[0-9]+)(?:\s*[+\-*/]\s*(?:[0-9]*[a-zA-Z]|[0-9]+))+)\b", text):
            if re.search(r"[a-zA-Z]", ex.group(1)):
                add_cand(ex.group(1), "expression")
        for st in re.finditer(r"\b([0-9]+[a-zA-Z])\b", text):
            add_cand(st.group(1), "expression")

        # Standalone numbers e.g. "40", "40.0"
        if not has_equation:
            for nm in re.finditer(r"\b(-?\d+(?:\.\d+)?)\b", text):
                if not is_in_negation(nm.start(1), nm.end(1), nm.group(1).strip()):
                    add_cand(nm.group(1), "number")

    return candidates


def normalize_expression(expr: str) -> str:
    """Normalize simple commutative addition expressions e.g. '2p + h' == 'h + 2p'."""
    clean = expr.lower().replace(" ", "")
    if "+" in clean:
        parts = sorted(clean.split("+"))
        return "+".join(parts)
    return clean


def verify_math_equivalence(candidate: str, expected: str, expected_type: str) -> bool:
    """Deterministically check if candidate student answer matches expected answer."""
    cand = candidate.strip()
    exp = expected.strip()

    # Exact string match (case-insensitive)
    if cand.lower() == exp.lower():
        return True

    # Equation comparison: e.g. "x = 4" vs "4" or "x = 4"
    if expected_type == "equation":
        cand_eq = re.search(r"\b([a-zA-Z])\s*=\s*(.+)$", cand)
        exp_eq = re.search(r"\b([a-zA-Z])\s*=\s*(.+)$", exp)
        cand_val = cand_eq.group(2).strip() if cand_eq else cand
        exp_val = exp_eq.group(2).strip() if exp_eq else exp
        # Check if variable names match if both provided
        if cand_eq and exp_eq and cand_eq.group(1).lower() != exp_eq.group(1).lower():
            return False
        # Compare RHS values mathematically
        f_cand = parse_fraction_or_num(cand_val)
        f_exp = parse_fraction_or_num(exp_val)
        if f_cand is not None and f_exp is not None:
            return f_cand == f_exp
        return cand_val.lower() == exp_val.lower()

    # Numeric or Fraction comparison: handles 3/4 == 6/8 == 0.75, 1 1/2 == 3/2, 40 == 40.0
    if expected_type in ("number", "fraction"):
        f_cand = parse_fraction_or_num(cand)
        f_exp = parse_fraction_or_num(exp)
        if f_cand is not None and f_exp is not None:
            return f_cand == f_exp

    # Algebraic expression comparison: e.g. "2p + h" vs "h + 2p"
    if expected_type == "expression":
        return normalize_expression(cand) == normalize_expression(exp)

    return False


def evaluate_student_solution(student_message: str, current_problem: dict) -> dict:
    """
    Objective Math Evaluator entry point.
    Returns:
    {
        "objective_solved": bool,
        "is_explicit_attempt": bool,
        "student_answer_extracted": str | None,
        "expected_answer": str | None,
        "eval_type": str,
        "match_reason": str,
    }
    """
    expected_ans, expected_type = extract_expected_answer(current_problem)
    if not expected_ans:
        return {
            "objective_solved": False,
            "is_explicit_attempt": False,
            "student_answer_extracted": None,
            "expected_answer": None,
            "eval_type": "none",
            "match_reason": "No ground truth answer available for problem",
        }

    candidates = extract_student_candidate(student_message)

    # Check if student made an explicit answer claim (e.g. mentions "answer", "equals", or bare candidate)
    msg_lower = student_message.lower()
    explicit_answer_intent = any(k in msg_lower for k in [
        "answer is", "answer:", "is it", "got", "equals", "equal to", "i think it's", "it is", "result is", "= "
    ])

    matched_candidate = None
    is_match = False

    # Check all extracted candidates against expected answer
    for cand, c_type in candidates:
        if verify_math_equivalence(cand, expected_ans, expected_type):
            is_match = True
            matched_candidate = cand
            break

    # If not matched, pick most prominent candidate to detect incorrect final attempts
    chosen_candidate = matched_candidate or (candidates[0][0] if candidates else None)
    is_attempt = explicit_answer_intent or bool(candidates and len(student_message.split()) <= 4)

    return {
        "objective_solved": is_match,
        "is_explicit_attempt": is_attempt,
        "student_answer_extracted": chosen_candidate,
        "expected_answer": expected_ans,
        "eval_type": expected_type,
        "match_reason": f"Mathematically verified equivalence with expected {expected_ans}" if is_match else (
            f"Candidate '{chosen_candidate}' is not equivalent to expected '{expected_ans}'" if chosen_candidate else "No numerical or algebraic candidate found"
        ),
    }
