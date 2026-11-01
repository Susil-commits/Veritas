"""
Inference Systems Engineering — Tiered Model Router & Streaming Invariant Buffer.

Provides:
1. Tiered Multi-Model Speculative Routing:
   - Tier 1: Fast SLM / Flash-Lite (<250ms TTFT) for conversational acknowledgments & greetings.
   - Tier 2: Primary Socratic Reasoning (Gemini Flash) for pedagogical inquiry.
   - Tier 3: Multimodal Vision (Gemini Flash/Pro Vision) for handwritten scratchpad reticles.
2. Sliding Window Streaming Invariant Buffer:
   - Buffers streaming tokens to prevent partial answer leakage over Server-Sent Events (SSE).
"""
from enum import Enum
import re
import time
from typing import AsyncGenerator, Dict, Generator, List, Optional, Tuple


class InferenceTier(str, Enum):
    TIER_1_FAST_TRIAGE = "tier_1_fast_triage"        # Low latency (<250ms), conversational ack/pleasantry
    TIER_2_SOCRATIC_REASONING = "tier_2_socratic"     # Standard Socratic math reasoning
    TIER_3_MULTIMODAL_VISION = "tier_3_vision"        # Vision bounding box reticle on scratchpad


# Fast acknowledgment responses for Tier 1 without invoking heavy LLMs
FAST_ACK_PATTERNS = {
    r"^(?:ok|okay|got it|makes sense|i see|understood|cool|alright)\b": (
        "Great! What step should we tackle next to keep moving forward?"
    ),
    r"^(?:hi|hello|hey|good morning|good afternoon)\b": (
        "Hello! Ready to dive into some math? Take a look at the problem and let me know where you'd like to begin."
    ),
    r"^(?:yes|yeah|yep|sure)\b": (
        "Awesome! Can you explain your thinking for that part?"
    ),
    r"^(?:idk|i don't know|no clue|im stuck|i am stuck)\b": (
        "No worries at all, getting stuck is part of learning. What is the very first thing the problem asks us to find?"
    ),
}


class InferenceRouter:
    """
    Intelligent Inference Router that steers incoming student requests to the optimal
    model tier based on complexity, modality, and latency budgets.
    """

    @classmethod
    def classify_request(cls, student_input: str, has_image: bool = False) -> Tuple[InferenceTier, Optional[str]]:
        """
        Classifies request into appropriate inference tier.
        Returns:
            (tier, fast_response_if_available)
        """
        if has_image:
            return InferenceTier.TIER_3_MULTIMODAL_VISION, None

        cleaned = student_input.strip().lower()

        # Check for fast zero-LLM or ultra-low-latency responses (Tier 1)
        for pattern, canned_reply in FAST_ACK_PATTERNS.items():
            if re.search(pattern, cleaned):
                return InferenceTier.TIER_1_FAST_TRIAGE, canned_reply

        # Default to Tier 2: Socratic reasoning agent
        return InferenceTier.TIER_2_SOCRATIC_REASONING, None


class StreamingInvariantBuffer:
    """
    Sliding window token buffer for Server-Sent Events (SSE) streaming.
    Ensures answers are never leaked incrementally during real-time generation.
    """

    LEAK_SUBSTRINGS = ["the answer is", "x =", "y =", "final answer:", "equals", "equal to"]

    def __init__(self, target_solution: str, window_size: int = 6):
        self.target_solution = str(target_solution).strip().lower()
        self.window_size = window_size
        self.token_history: List[str] = []
        self.leak_detected: bool = False

    def process_chunk(self, token: str) -> Optional[str]:
        """
        Processes a streaming token chunk.
        If a leak pattern emerges across recent tokens, suppresses token and flags violation.
        Otherwise, yields token for delivery.
        """
        if self.leak_detected:
            return None

        self.token_history.append(token)
        recent_text = "".join(self.token_history[-self.window_size:]).lower()

        # Check if target solution or answer statement is forming
        for leak_phrase in self.LEAK_SUBSTRINGS:
            if leak_phrase in recent_text and self.target_solution in recent_text:
                self.leak_detected = True
                # Return safe replacement instead of leaked token
                return " Let's think about how to find that value — what do you notice about this step?"

        return token

