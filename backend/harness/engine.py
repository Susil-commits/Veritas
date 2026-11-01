"""
Veritas Execution Harness — Deterministic Sandbox, Invariant Gate, and Replay Engine.

Coordinates:
1. Pre-inference input verification and sanitization.
2. Controlled execution of LLM generation.
3. Post-inference invariant gate: Zero Answer Leakage & Socratic Inquiry checks.
4. Deterministic safe fallback on invariant violation.
5. Replay trace logging.
"""
import time
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .invariants import PedagogicalInvariantChecker
from .sandbox import SafeMathEvaluator

logger = logging.getLogger("veritas-backend.harness")

SAFE_SOCRATIC_FALLBACKS = [
    "What operation do you think we should focus on first in this step?",
    "Let's look at the numbers on the left side — how can we simplify them?",
    "Could you walk me through the rule you used in this step?",
    "Notice the relationship between these two terms — what do you observe?",
]


class VeritasExecutionHarness:
    """
    Production execution harness wrapping stochastic LLM calls with deterministic invariants.
    """

    def __init__(self, record_traces: bool = True):
        self.record_traces = record_traces
        self.session_traces: List[Dict[str, Any]] = []

    def execute_turn(
        self,
        tutor_callable: Callable[[], str],
        target_solution: str,
        student_input: str,
        prohibited_expressions: Optional[List[str]] = None,
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        Executes a tutor turn with invariant verification and automatic safe fallback.

        Returns:
            Dict containing:
                - verified_reply: Safe, verified tutor reply string.
                - invariant_status: Result of invariant validation.
                - used_fallback: Boolean indicating whether an invariant failure triggered safe fallback.
                - latency_ms: Execution duration in milliseconds.
        """
        start_time = time.perf_counter()
        attempts = 0
        last_validation = None
        raw_reply = ""

        while attempts < max_retries:
            attempts += 1
            try:
                raw_reply = tutor_callable()
            except Exception as e:
                logger.error(f"Harness: Tutor callable raised exception: {e}")
                raw_reply = ""

            validation = PedagogicalInvariantChecker.validate_all(
                tutor_reply=raw_reply,
                target_solution=target_solution,
                prohibited_expressions=prohibited_expressions
            )
            last_validation = validation

            if validation["passed"]:
                latency_ms = (time.perf_counter() - start_time) * 1000
                result = {
                    "verified_reply": raw_reply,
                    "invariant_status": validation,
                    "used_fallback": False,
                    "attempts": attempts,
                    "latency_ms": round(latency_ms, 2)
                }
                self._record_trace(student_input, target_solution, result)
                return result

            logger.warning(
                f"Harness: Turn generation failed invariants on attempt {attempts}/{max_retries}. "
                f"Details: {validation}"
            )

        # Invariant failed on all attempts -> trigger deterministic safe Socratic fallback
        fallback_reply = SAFE_SOCRATIC_FALLBACKS[hash(student_input) % len(SAFE_SOCRATIC_FALLBACKS)]
        latency_ms = (time.perf_counter() - start_time) * 1000

        result = {
            "verified_reply": fallback_reply,
            "invariant_status": last_validation,
            "used_fallback": True,
            "attempts": attempts,
            "latency_ms": round(latency_ms, 2),
            "original_rejected_reply": raw_reply
        }
        self._record_trace(student_input, target_solution, result)
        return result

    def _record_trace(self, student_input: str, target_solution: str, result: Dict[str, Any]) -> None:
        if not self.record_traces:
            return
        self.session_traces.append({
            "timestamp": time.time(),
            "student_input": student_input,
            "target_solution": target_solution,
            "result": result
        })

