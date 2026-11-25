"""
Unified Google GenAI (`google.genai`) client wrapper for Veritas.

Replaces the deprecated `langchain_google_genai` / `google.generativeai` stack
with native `google.genai.Client` calls while preserving the `.invoke(messages)`
and `.embed_documents(...)` / `.embed_query(...)` interfaces expected across
agents, scripts, and unit test mocks.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any, Iterable

from google import genai
from google.genai import types
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config import EMBEDDING_DIMENSION

logger = logging.getLogger("veritas.gemini_client")

_DATA_URI_RE = re.compile(r"^data:([^;]+);base64,(.+)$", flags=re.DOTALL)
_CLIENT_CACHE: dict[str, genai.Client] = {}


def _get_api_key(explicit_key: str | None = None) -> str:
    return explicit_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")


def _get_genai_client(api_key: str | None = None) -> genai.Client:
    key = _get_api_key(api_key)
    cached = _CLIENT_CACHE.get(key)
    if cached is None:
        cached = genai.Client(api_key=key)
        _CLIENT_CACHE[key] = cached
    return cached


def _part_from_block(block: Any) -> types.Part | None:
    if isinstance(block, str):
        return types.Part.from_text(text=block)
    if isinstance(block, dict):
        b_type = block.get("type")
        if b_type == "text":
            return types.Part.from_text(text=str(block.get("text", "")))
        if b_type == "image_url":
            image_url = block.get("image_url")
            url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url or "")
            m = _DATA_URI_RE.match(url.strip())
            if m:
                mime_type = m.group(1) or "image/jpeg"
                raw_bytes = base64.b64decode(m.group(2))
                return types.Part.from_bytes(data=raw_bytes, mime_type=mime_type)
    return None


def _convert_messages(messages: Iterable[BaseMessage | dict[str, Any]]) -> tuple[str | None, list[types.Content]]:
    """Convert LangChain BaseMessage objects to Gemini system_instruction + Content list."""
    system_parts: list[str] = []
    contents: list[types.Content] = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if text:
                system_parts.append(text)
            continue

        if isinstance(msg, AIMessage):
            role = "model"
            raw_content = msg.content
        elif isinstance(msg, HumanMessage):
            role = "user"
            raw_content = msg.content
        elif isinstance(msg, dict):
            msg_role = str(msg.get("role", "user")).lower()
            if msg_role == "system":
                if msg.get("content"):
                    system_parts.append(str(msg["content"]))
                continue
            role = "model" if msg_role in ("assistant", "model", "tutor", "ai") else "user"
            raw_content = msg.get("content", "")
        else:
            role = "user"
            raw_content = getattr(msg, "content", "")

        parts: list[types.Part] = []
        if isinstance(raw_content, list):
            for item in raw_content:
                part = _part_from_block(item)
                if part is not None:
                    parts.append(part)
        else:
            text_val = str(raw_content or "")
            if text_val:
                parts.append(types.Part.from_text(text=text_val))

        if parts:
            contents.append(types.Content(role=role, parts=parts))

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


class GeminiChatWrapper:
    """Drop-in LangChain-compatible chat wrapper powered by native `google.genai`."""

    def __init__(
        self,
        model: str,
        google_api_key: str = "",
        max_output_tokens: int = 1000,
        temperature: float | None = None,
        max_retries: int = 0,
        timeout: float = 10.0,
    ) -> None:
        self.model = model
        self.api_key = _get_api_key(google_api_key)
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout

    def invoke(self, messages: Iterable[BaseMessage | dict[str, Any]]) -> AIMessage:
        client = _get_genai_client(self.api_key)
        system_instruction, contents = _convert_messages(messages)

        config_kwargs: dict[str, Any] = {
            "max_output_tokens": self.max_output_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if self.temperature is not None:
            config_kwargs["temperature"] = self.temperature
        if self.timeout and self.timeout > 0:
            config_kwargs["http_options"] = types.HttpOptions(timeout=int(self.timeout * 1000))

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return AIMessage(content=(response.text or ""))

    def _build_config_and_contents(
        self,
        messages: Iterable[BaseMessage | dict[str, Any]],
    ) -> tuple[list[types.Content], types.GenerateContentConfig]:
        system_instruction, contents = _convert_messages(messages)
        config_kwargs: dict[str, Any] = {
            "max_output_tokens": self.max_output_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if self.temperature is not None:
            config_kwargs["temperature"] = self.temperature
        if self.timeout and self.timeout > 0:
            config_kwargs["http_options"] = types.HttpOptions(timeout=int(self.timeout * 1000))
        return contents, types.GenerateContentConfig(**config_kwargs)

    def stream(self, messages: Iterable[BaseMessage | dict[str, Any]]) -> Iterable[str]:
        """Yield text deltas directly from google.genai.models.generate_content_stream."""
        client = _get_genai_client(self.api_key)
        contents, config = self._build_config_and_contents(messages)
        for chunk in client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        ):
            delta = getattr(chunk, "text", None)
            if delta:
                yield str(delta)


class GeminiEmbeddingWrapper:
    """Drop-in embedding wrapper powered by native `google.genai`."""

    def __init__(
        self,
        model: str,
        google_api_key: str = "",
        output_dimensionality: int = EMBEDDING_DIMENSION,
    ) -> None:
        self.model = model
        self.api_key = _get_api_key(google_api_key)
        self.output_dimensionality = output_dimensionality

    def embed_documents(
        self,
        texts: list[str],
        output_dimensionality: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        client = _get_genai_client(self.api_key)
        dim = output_dimensionality or self.output_dimensionality
        response = client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=dim),
        )
        embeddings = getattr(response, "embeddings", None) or []
        return [list(getattr(item, "values", []) or []) for item in embeddings]

    def embed_query(
        self,
        text: str,
        output_dimensionality: int | None = None,
    ) -> list[float]:
        vectors = self.embed_documents([text], output_dimensionality=output_dimensionality)
        return vectors[0] if vectors else []
