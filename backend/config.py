"""Shared configuration utilities for RefereeOS.

Centralizes LLM configuration and common helpers used by both
``orchestrator.py`` and ``ag2_reviewer.py`` to avoid code duplication.
"""

from __future__ import annotations

import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# API key helpers
# ---------------------------------------------------------------------------


def gemini_api_key() -> str:
    """Return the first available Gemini/Google API key, or empty string."""
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    )


def deepseek_api_key() -> str:
    """Return the DeepSeek API key, or empty string."""
    return os.getenv("DEEPSEEK_API_KEY") or ""


def any_llm_api_key() -> str:
    """Return the first available API key among all supported providers."""
    return gemini_api_key() or deepseek_api_key()


# ---------------------------------------------------------------------------
# LLM config builders
# ---------------------------------------------------------------------------


def build_llm_config_dict(
    model: str | None = None,
) -> dict[str, str] | None:
    """Build a plain dict describing the LLM configuration.

    Returns ``None`` when no API key is configured.  Callers that need an
    ``OpenAIConfig`` or ``GeminiConfig`` object should use
    ``build_llm_config()`` instead.
    """
    gkey = gemini_api_key()
    if gkey:
        return {
            "model": model or os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview"),
            "api_key": gkey,
            "api_type": "google",
            "base_url": "",
        }
    dkey = deepseek_api_key()
    if dkey:
        ds_model = model or os.getenv("AG2_MODEL", "deepseek-v4-pro")
        return {
            "model": ds_model,
            "api_key": dkey,
            "api_type": "openai",
            "base_url": os.getenv("AG2_BASE_URL", "https://api.deepseek.com/v1"),
        }
    return None


def build_llm_config(model: str | None = None, temperature: float = 0):
    """Build an ``OpenAIConfig`` or ``GeminiConfig`` for AG2 Beta agents.

    Raises ``SystemExit`` when no API key is available (suitable for CLI use).
    For server-side code, check ``any_llm_api_key()`` first.
    """
    from autogen.beta.config import GeminiConfig, OpenAIConfig  # type: ignore

    gkey = gemini_api_key()
    if gkey:
        m = model or os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
        return GeminiConfig(model=m, api_key=gkey, temperature=temperature)

    dkey = deepseek_api_key()
    if dkey:
        m = model or os.getenv("AG2_MODEL", "deepseek-v4-pro")
        base_url = os.getenv("AG2_BASE_URL", "https://api.deepseek.com/v1")
        extra = {"thinking": {"type": "disabled"}} if "deepseek" in m.lower() else {}
        return OpenAIConfig(
            model=m,
            api_key=dkey,
            base_url=base_url,
            temperature=temperature,
            extra_body=extra,
        )

    raise SystemExit(
        "ERROR: No LLM API key found. Set DEEPSEEK_API_KEY or GEMINI_API_KEY in .env"
    )


# ---------------------------------------------------------------------------
# Claim classification
# ---------------------------------------------------------------------------

# Pre-compiled regexes for word-boundary matching
_BENCHMARK_PATTERNS = [re.compile(r"\bf1\b"), re.compile(r"\bbenchmark\b"), re.compile(r"\boutperform\b")]
_METHOD_PATTERNS = [re.compile(r"\bmethod\b"), re.compile(r"\bfeature\b")]
_CAUSAL_PATTERNS = [re.compile(r"\bcausal\b"), re.compile(r"\bproves?\b")]


def classify_claim(text: str) -> str:
    """Classify a scientific claim into a type using word-boundary regex.

    Returns one of: ``"causal"``, ``"benchmark"``, ``"methodological"``, ``"empirical"``.
    """
    lowered = text.lower()
    if any(p.search(lowered) for p in _CAUSAL_PATTERNS):
        return "causal"
    if any(p.search(lowered) for p in _BENCHMARK_PATTERNS):
        return "benchmark"
    if any(p.search(lowered) for p in _METHOD_PATTERNS):
        return "methodological"
    return "empirical"
