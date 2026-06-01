"""LLM factory: task -> chat model, with provider + model routing.

Default provider is Google Gemini (works with a Gemini Flash API key). The
agent is provider-agnostic: every node calls `llm(task)` / `structured(task, ...)`
here and never imports a provider SDK, so swapping providers is a config change.

Set MODEL_PROVIDER=anthropic to use Claude instead. Instantiation is lazy and
import-safe: importing this module never requires an API key. Tests inject fakes
by monkeypatching `llm` / `structured`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from . import config

PROVIDER = os.getenv("MODEL_PROVIDER", "google").lower()


@lru_cache(maxsize=32)
def _build(model_id: str, temperature: float):
    """Construct a chat model for the active provider. Lazy imports keep the
    package importable without the provider package / API key installed."""
    if PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # Accepts GOOGLE_API_KEY or GEMINI_API_KEY from the environment.
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        kwargs = {"model": model_id, "temperature": temperature, "max_tokens": 2048}
        if api_key:
            kwargs["google_api_key"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)

    if PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_id, temperature=temperature, max_tokens=2048)

    raise ValueError(f"Unknown MODEL_PROVIDER={PROVIDER!r} (expected 'google' or 'anthropic')")


def llm(task: str, tier: Optional[str] = None, temperature: float = 0.3):
    """Return a chat model for a task. Override in tests by monkeypatching this fn."""
    model_id = config.model_for(task, tier)
    return _build(model_id, temperature)


def structured(task: str, schema, tier: Optional[str] = None, temperature: float = 0.0):
    """Return a model bound to emit a Pydantic schema (scoring/classification)."""
    return llm(task, tier=tier, temperature=temperature).with_structured_output(schema)
