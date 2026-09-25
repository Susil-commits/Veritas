"""
Centralized AI Model & Infrastructure Configuration — Veritas.
Single source of truth for Gemini model names, embedding specifications, and cascades.
"""
import ast
import os
from typing import Any

# Primary chat & Socratic dialogue LLM (500 RPD / 15 RPM on Free Tier)
CHAT_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Diagnostic vision model for handwritten math OCR and misconception localization
VISION_MODEL: str = os.getenv("GEMINI_VISION_MODEL", "gemini-3.5-flash-lite")

# Text embedding model for pgvector semantic search & RAG
EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))

# Cascade fallback models for chat — override via .env if needed
# Priority: GEMINI_MODEL → GEMINI_MODEL_FALLBACK_1 → GEMINI_MODEL_FALLBACK_2
_CHAT_FALLBACK_1: str = os.getenv("GEMINI_MODEL_FALLBACK_1", "gemini-3.8-flash")
_CHAT_FALLBACK_2: str = os.getenv("GEMINI_MODEL_FALLBACK_2", "gemini-flash-lite-latest")

# dict.fromkeys preserves order and deduplicates (e.g. if primary == fallback_1)
CHAT_MODEL_CASCADE: list[str] = list(dict.fromkeys(
    m for m in [CHAT_MODEL, _CHAT_FALLBACK_1, _CHAT_FALLBACK_2] if m
))

# Cascade fallback models for vision/OCR — override via .env if needed
# Priority: GEMINI_VISION_MODEL → GEMINI_VISION_MODEL_FALLBACK_1 → GEMINI_VISION_MODEL_FALLBACK_2
_VISION_FALLBACK_1: str = os.getenv("GEMINI_VISION_MODEL_FALLBACK_1", "gemini-3.8-flash")
_VISION_FALLBACK_2: str = os.getenv("GEMINI_VISION_MODEL_FALLBACK_2", "gemini-flash-lite-latest")

VISION_MODEL_CASCADE: list[str] = list(dict.fromkeys(
    m for m in [VISION_MODEL, _VISION_FALLBACK_1, _VISION_FALLBACK_2] if m
))


def extract_clean_text(content: Any) -> str:
    """
    Safely extract flat, clean text from LangChain / Google GenAI response content.
    Handles str, list[str], list[dict], or stringified Python lists like "['part1', 'part2']".
    Prevents raw Python list representations from leaking to users.
    """
    if not content:
        return ""

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", item.get("content", ""))))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
            elif hasattr(item, "content"):
                parts.append(str(item.content))
            else:
                parts.append(str(item))
        text = "".join(parts).strip()
    else:
        text = str(content).strip()

    # Catch if text itself is formatted as a stringified Python list of strings
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                text = "".join(str(p) for p in parsed).strip()
        except Exception:
            pass

    return text

