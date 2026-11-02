"""
Harness Engineering — Pedagogical Invariants and Safety Assertions.

Enforces:
1. Zero Answer Leakage (deterministic numeric, algebraic, and fractional equivalence).
2. Socratic Active Inquiry (response must contain a guiding question).
3. Brevity & Non-Lecture Invariant (keeps tutor answers short and focused).
"""
import re
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple


class InvariantViolation(Exception):
    """Raised when an AI generation breaks a foundational pedagogical or safety invariant."""
    pass


class PedagogicalInvariantChecker:
    """
    Evaluates tutor replies against strict deterministic pedagogical invariants.
    """

    QUESTION_INDICATORS = [
        "?", "what", "how", "why", "can you", "could you", "notice",
        "where", "which", "do you see", "think about", "what if"
    ]

    LEAK_PATTERNS = [
        r"\b(?:the\s+)?answer\s+is\s+([^\.,;!\?]+)",
        r"\b(?:x|y|z|n)\s*=\s*([^\.,;!\?]+)",
        r"\b(?:it\s+equals|equal\s+to)\s+([^\.,;!\?]+)",
        r"\b(?:solution\s+is)\s+([^\.,;!\?]+)",
        r"\b(?:final\s+answer)\s*:\s*([^\.,;!\?]+)",
    ]

    @staticmethod
    def _parse_fraction_or_num(raw: str) -> Optional[Fraction]:
        """Helper to parse numeric/fractional strings safely."""
        cleaned = raw.replace(",", "").lstrip("$").rstrip("$").strip()
        m_frac = re.match(r"^(-?\d+)/(\d+)$", cleaned)
        if m_frac:
            try:
                num, den = int(m_frac.group(1)), int(m_frac.group(2))
                return Fraction(num, den) if den != 0 else None
            except Exception:
                return None
        try:
            return Fraction(float(cleaned)).limit_denominator(10000)
        except Exception:
            return None

    @classmethod
    def check_zero_answer_leakage(
        cls,
        tutor_reply: str,
        target_solution: str,
        prohibited_expressions: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Asserts that the tutor reply does NOT leak the target solution.
        Checks:
        1. Explicit leak triggers ("the answer is X").
        2. Direct token presence of the target solution number/fraction.
        3. Prohibited expression substrings.
        """
        reply_lower = tutor_reply.lower()
        target_clean = str(target_solution).strip()
        target_frac = cls._parse_fraction_or_num(target_clean)

        # 0. Multi-pattern Socratic leak verification
        try:
            from backend.safety import is_answer_leaked
        except ImportError:
            try:
                from safety import is_answer_leaked
            except ImportError:
                is_answer_leaked = None
        if is_answer_leaked and is_answer_leaked(tutor_reply, target_solution):
            return False, f"Direct answer leak: Target solution '{target_clean}' detected in reply"

        # 1. Regex Leak Patterns
        for pattern in cls.LEAK_PATTERNS:
            match = re.search(pattern, reply_lower, re.IGNORECASE)
            if match:
                full_matched = match.group(0).strip()
                extracted = match.group(1).strip()
                extracted_frac = cls._parse_fraction_or_num(extracted)
                if extracted_frac and target_frac and extracted_frac == target_frac:
                    return False, f"Direct answer leak detected matching pattern '{pattern}': '{extracted}' == '{target_clean}'"
                if target_clean.lower() in extracted.lower() or target_clean.lower() in full_matched.lower():
                    return False, f"Target solution substring found inside leak pattern: '{extracted}'"
                if re.sub(r"\s+", "", target_clean.lower()) in re.sub(r"\s+", "", full_matched.lower()):
                    return False, f"Target solution expression found inside leak pattern: '{full_matched}'"

        # 1b. Direct Normalized Target Match (e.g. 'x = 5' or '3/4')
        target_norm = re.sub(r"\s+", "", target_clean.lower())
        reply_norm = re.sub(r"\s+", "", reply_lower)
        if len(target_norm) >= 3 and target_norm in reply_norm:
            if "=" in target_clean or "/" in target_clean:
                return False, f"Target solution '{target_clean}' found directly in tutor reply"

        # 2. Strict Numerical / Isolated Token Check
        # If target is a number like "42" or "3/4", ensure it's not bluntly asserted as a solitary calculation result
        if target_frac is not None:
            # Look for isolated tokens in the reply that match the fraction value
            tokens = re.findall(r"[-+]?\d+(?:/\d+|\.\d+)?", reply_lower)
            for tok in tokens:
                tok_frac = cls._parse_fraction_or_num(tok)
                if tok_frac and tok_frac == target_frac:
                    # Check context: is the tutor stating the answer or just repeating problem constants?
                    # If surrounded by "answer is <tok>" or "= <tok>", it's an invariant breach
                    context_window = reply_lower[max(0, reply_lower.find(tok) - 20) : min(len(reply_lower), reply_lower.find(tok) + len(tok) + 20)]
                    if any(term in context_window for term in ["answer", "equals", "equal to", "result is", "gives you", "is "]):
                        return False, f"Numeric target solution '{tok}' directly asserted in context '{context_window}'"

        # 3. Prohibited Expressions
        if prohibited_expressions:
            for expr in prohibited_expressions:
                if expr.lower().strip() in reply_lower:
                    return False, f"Prohibited milestone expression '{expr}' leaked in reply"

        return True, None

    @classmethod
    def check_socratic_inquiry(cls, tutor_reply: str) -> Tuple[bool, Optional[str]]:
        """
        Asserts that the tutor reply engages the student via an open question.
        Must contain a question mark or recognized Socratic inquiry prompt.
        """
        reply_clean = tutor_reply.strip()
        if not reply_clean:
            return False, "Tutor reply is empty"

        has_question_mark = "?" in reply_clean
        reply_lower = reply_clean.lower()
        has_inquiry_term = any(ind in reply_lower for ind in cls.QUESTION_INDICATORS)

        if not has_question_mark and not has_inquiry_term:
            return False, "Tutor reply does not contain a question mark or Socratic inquiry prompt."

        return True, None

    @classmethod
    def check_conciseness(cls, tutor_reply: str, max_sentences: int = 4) -> Tuple[bool, Optional[str]]:
        """
        Asserts that the tutor does not give a lecture.
        Should not exceed max_sentences.
        """
        # Split sentences roughly on '.', '!', '?'
        sentences = [s.strip() for s in re.split(r"[.!?]+", tutor_reply) if s.strip()]
        if len(sentences) > max_sentences:
            return False, f"Tutor reply contains {len(sentences)} sentences (max allowed is {max_sentences})."

        return True, None

    @classmethod
    def validate_all(
        cls,
        tutor_reply: str,
        target_solution: str,
        prohibited_expressions: Optional[List[str]] = None,
        max_sentences: int = 4
    ) -> Dict[str, Any]:
        """
        Runs the full pedagogical invariant test suite on a candidate tutor reply.
        """
        leak_ok, leak_reason = cls.check_zero_answer_leakage(tutor_reply, target_solution, prohibited_expressions)
        inquiry_ok, inquiry_reason = cls.check_socratic_inquiry(tutor_reply)
        brevity_ok, brevity_reason = cls.check_conciseness(tutor_reply, max_sentences)

        all_passed = leak_ok and inquiry_ok and brevity_ok
        return {
            "passed": all_passed,
            "zero_leakage": {"passed": leak_ok, "error": leak_reason},
            "socratic_inquiry": {"passed": inquiry_ok, "error": inquiry_reason},
            "brevity": {"passed": brevity_ok, "error": brevity_reason},
        }
