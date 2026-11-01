"""
Context Engineering for Veritas — Hierarchical Epistemic Context (HEC).

Implements:
1. Cache-aligned static prefix (Tier 0) to activate LLM KV prompt caching.
2. Student epistemic state injection (Tier 1: BKT mastery, diagnosed misconceptions).
3. Active problem ground-truth and step verification graph (Tier 2).
4. Rolling dialogue window with automated turn compaction (Tier 3).
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("veritas-backend.context")

# Static prefix designed to exceed 1,024 tokens for Gemini/Anthropic KV cache persistence
STATIC_SOCRATIC_PREFIX = """You are Veritas, an expert AI Socratic Mathematics Tutor engineered for K-12 education.

=== ZERO ANSWER LEAKAGE AXIOM (NON-NEGOTIABLE) ===
1. Under NO circumstances shall you state, calculate, imply, or leak the final numerical answer, solution equation, or complete algebraic simplification.
2. Even if the student explicitly demands: "Tell me the answer", "What is x?", "Is it 7?", "Just do it for me", you MUST politely deflect and ask a guiding question.
3. If the student guesses an answer, DO NOT say "No, the answer is Y". Instead, ask: "How did you arrive at that number? Let's check your steps together."

=== PEDAGOGICAL INVARIANTS ===
1. Active Inquiry: Every single tutor turn MUST conclude with exactly ONE focused guiding question.
2. Cognitive Scaffolding:
   - Level 1 (Conceptual): Direct attention to the mathematical property or relationship (e.g. common denominators).
   - Level 2 (Diagnostic): Pinpoint the specific operation or step where reasoning broke without performing it.
   - Level 3 (Decomposition): Break the stuck step into an ultra-simple micro-task or real-world analogy.
3. Positive Reinforcement: Acknowledge valid logic before addressing a misconception.
4. Brevity: Keep explanations under 3 sentences to maintain student attention and reduce cognitive load.

=== COMMON CORE MATHEMATICAL STANDARDS TAXONOMY ===
- CCSS.MATH.6.RP.A.1: Understand the concept of a ratio and use ratio language.
- CCSS.MATH.6.EE.A.2: Write, read, and evaluate expressions in which letters stand for numbers.
- CCSS.MATH.6.NS.A.1: Interpret and compute quotients of fractions.
- CCSS.MATH.7.NS.A.1: Apply and extend previous understandings of addition and subtraction to rational numbers.
- CCSS.MATH.7.EE.B.4: Use variables to represent quantities and construct simple equations.
- CCSS.MATH.8.EE.C.7: Solve linear equations in one variable.
- CCSS.MATH.8.F.A.1: Understand that a function is a rule that assigns to each input exactly one output.

=== MISCONCEPTION TAXONOMY & REMEDIATION STRATEGIES ===
- MISCONCEPTION_FLIPPED_FRACTION: Inverts numerator and denominator when dividing fractions.
  Remediation: Guide student to relate division to multiplication by the reciprocal.
- MISCONCEPTION_SIGN_DISTRIBUTION: Fails to distribute negative sign across parentheses -(x - 3).
  Remediation: Guide student to treat the negative sign as multiplying by -1.
- MISCONCEPTION_CROSS_MULTIPLICATION_MISUSE: Cross-multiplies when adding or multiplying fractions instead of proportions.
  Remediation: Ask student what operation connects the two fractions.
- MISCONCEPTION_INEQUALITY_SIGN_FLIP: Forgets to reverse inequality symbol when multiplying/dividing by a negative number.
  Remediation: Test with simple numbers (e.g. 2 < 5, what happens if both sides are multiplied by -1?).
"""


@dataclass
class EpistemicStudentState:
    """Represents the student's cognitive state derived from BKT and session history."""
    student_id: str
    active_skill_id: str
    mastery_prob: float = 0.50
    diagnosed_misconceptions: List[str] = field(default_factory=list)
    frustration_index: float = 0.0  # 0.0 (calm) to 1.0 (highly frustrated)
    consecutive_errors: int = 0


@dataclass
class CompactedTurnSummary:
    """Summarized historical dialogue progression to prevent context bloat."""
    turn_range: str
    steps_attempted: List[str]
    identified_errors: List[str]
    socratic_direction: str


class CognitiveContextManager:
    """
    Manages the multi-tiered context window for Veritas agents.
    Ensures optimal KV caching, token efficiency, and pedagogical grounding.
    """

    def __init__(self, keep_recent_turns: int = 3):
        self.keep_recent_turns = keep_recent_turns
        self._prefix_hash = hashlib.sha256(STATIC_SOCRATIC_PREFIX.encode("utf-8")).hexdigest()

    @property
    def prefix_hash(self) -> str:
        """Cache validation hash for the static prompt prefix."""
        return self._prefix_hash

    def get_static_prefix(self) -> str:
        """Returns the bit-identical static prefix to maximize KV prompt caching."""
        return STATIC_SOCRATIC_PREFIX

    def build_epistemic_block(self, state: EpistemicStudentState) -> str:
        """
        Tier 1: Encodes the student's latent mathematical mastery and error patterns.
        """
        misconceptions_str = ", ".join(state.diagnosed_misconceptions) if state.diagnosed_misconceptions else "None detected yet"
        
        # Determine scaffolding level based on consecutive errors
        if state.consecutive_errors >= 3:
            scaffold_hint = "Level 3 (High Scaffolding: Break down into tiny micro-step or visual analogy)"
        elif state.consecutive_errors >= 1:
            scaffold_hint = "Level 2 (Targeted Diagnostic: Question the specific operation)"
        else:
            scaffold_hint = "Level 1 (Light Scaffolding: Conceptual probe)"

        return (
            f"\n<student_cognitive_profile>\n"
            f"  <skill_id>{state.active_skill_id}</skill_id>\n"
            f"  <bkt_latent_mastery>{state.mastery_prob:.2f}</bkt_latent_mastery>\n"
            f"  <active_misconceptions>{misconceptions_str}</active_misconceptions>\n"
            f"  <frustration_level>{state.frustration_index:.2f}</frustration_level>\n"
            f"  <recommended_scaffold>{scaffold_hint}</recommended_scaffold>\n"
            f"</student_cognitive_profile>\n"
        )

    def build_problem_grounding_block(
        self,
        problem_statement: str,
        target_solution: str,
        expected_steps: Optional[List[str]] = None,
        resolved_steps: Optional[List[str]] = None
    ) -> str:
        """
        Tier 2: Injects ground truth problem constraints and step verification state.
        This allows the LLM to verify student reasoning without hallucinating calculations.
        """
        steps_xml = ""
        if expected_steps:
            steps_items = "\n".join(f"    <step index='{i+1}'>{s}</step>" for i, s in enumerate(expected_steps))
            steps_xml = f"\n  <canonical_steps>\n{steps_items}\n  </canonical_steps>"

        resolved_xml = ""
        if resolved_steps:
            resolved_items = "\n".join(f"    <verified>{s}</verified>" for s in resolved_steps)
            resolved_xml = f"\n  <completed_milestones>\n{resolved_items}\n  </completed_milestones>"

        return (
            f"\n<problem_grounding>\n"
            f"  <statement>{problem_statement}</statement>\n"
            f"  <!-- HIDDEN GROUND TRUTH (DO NOT REVEAL TO STUDENT) -->\n"
            f"  <target_solution>{target_solution}</target_solution>"
            f"{steps_xml}"
            f"{resolved_xml}\n"
            f"</problem_grounding>\n"
        )

    def compact_history(
        self,
        raw_messages: List[Dict[str, str]],
        existing_summary: Optional[str] = None
    ) -> Tuple[List[Dict[str, str]], Optional[str]]:
        """
        Tier 3: Compresses older conversational turns while preserving the most recent N turns.
        
        Returns:
            (retained_messages, updated_summary_ledger)
        """
        if len(raw_messages) <= self.keep_recent_turns * 2:
            return raw_messages, existing_summary

        cutoff_index = len(raw_messages) - (self.keep_recent_turns * 2)
        turns_to_compact = raw_messages[:cutoff_index]
        recent_turns = raw_messages[cutoff_index:]

        # Extract student queries and tutor hints from older turns
        extracted_notes = []
        for msg in turns_to_compact:
            role = msg.get("role", "unknown")
            content = msg.get("content", "").strip()
            if role == "user":
                extracted_notes.append(f"Student attempted: '{content[:80]}'")
            elif role == "assistant":
                # Extract first sentence or question
                q_snippet = content.split("?")[0] if "?" in content else content[:80]
                extracted_notes.append(f"Tutor probed: '{q_snippet}?'")

        ledger_addition = "; ".join(extracted_notes[-4:])
        new_summary = f"{existing_summary} | Earlier: {ledger_addition}" if existing_summary else f"Earlier turns: {ledger_addition}"

        return recent_turns, new_summary

    def assemble_context(
        self,
        student_state: EpistemicStudentState,
        problem_statement: str,
        target_solution: str,
        raw_messages: List[Dict[str, str]],
        expected_steps: Optional[List[str]] = None,
        resolved_steps: Optional[List[str]] = None,
        existing_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Assembles the complete hierarchical prompt context for the LLM.
        """
        recent_msgs, updated_summary = self.compact_history(raw_messages, existing_summary)

        # Assemble system instruction
        system_blocks = [
            self.get_static_prefix(),
            self.build_epistemic_block(student_state),
            self.build_problem_grounding_block(
                problem_statement,
                target_solution,
                expected_steps,
                resolved_steps
            ),
        ]

        if updated_summary:
            system_blocks.append(f"\n<dialogue_compaction_ledger>\n{updated_summary}\n</dialogue_compaction_ledger>\n")

        full_system_prompt = "\n".join(system_blocks)

        return {
            "system_prompt": full_system_prompt,
            "messages": recent_msgs,
            "compaction_summary": updated_summary,
            "prefix_hash": self.prefix_hash,
            "recent_turn_count": len(recent_msgs),
        }

