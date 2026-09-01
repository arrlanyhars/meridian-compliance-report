"""
A one-method interface so the provider is a plug, not a rewrite. Gemini is
the concrete implementation actually wired up (free tier, and one of the
explicitly acceptable providers for this project), but nothing in
generator.py or prompt.py knows that. They only see LLMClient.

Uses the `google-genai` package, not the older `google-generativeai` one.
Google retired the old package entirely ("no longer receiving updates or
bug fixes") and the model this was first built against, gemini-2.0-flash,
has since been removed server-side, so both the library and the model name
below are the current, actually-supported choices, not the ones this was
originally written with.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

# A .env file on disk does nothing on its own; something has to read it into
# the process environment. This loads it once, at import time, so a key
# placed in .env (per README.md / .env.example) works the same way an
# actually-exported shell variable would, without the user having to `export`
# it by hand every session. A real shell-exported GOOGLE_API_KEY still wins:
# load_dotenv() never overwrites a variable that's already set.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class LLMClient(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def generate(self, prompt: str) -> str: ...


class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(self, prompt: str) -> str:
        from google.genai import types

        # This never gives the model any tools to call, so automatic
        # function calling is irrelevant here; disabling it explicitly (the
        # SDK otherwise prints an unsolicited recommendation about it on
        # every call) is just naming that plainly rather than leaving a
        # default sitting unexamined.
        config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        response = self._client.models.generate_content(model=self._model_name, contents=prompt, config=config)
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text


def build_client_from_env() -> LLMClient | None:
    """None means "no narrative this run". The caller must handle that
    gracefully (SKIPPED_NO_API_KEY), not treat it as a pipeline failure."""
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    return GeminiClient(api_key)
