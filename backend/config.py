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
