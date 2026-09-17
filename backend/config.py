"""
Centralized AI Model & Infrastructure Configuration — Veritas / AINerd.
Single source of truth for Gemini model names, embedding specifications, and cascades.
"""
import os

# Primary chat & Socratic dialogue LLM
CHAT_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Diagnostic vision model for handwritten math OCR and misconception localization
VISION_MODEL: str = os.getenv("GEMINI_VISION_MODEL", "gemini-3.6-flash")

# Text embedding model for pgvector semantic search & RAG
EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))

# Resilience cascade for chat endpoints when primary model encounters quota/maintenance
CHAT_MODEL_CASCADE: list[str] = [
    CHAT_MODEL,
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]

import ast
from typing import Any

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

