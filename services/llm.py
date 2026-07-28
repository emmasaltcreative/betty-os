"""One place that talks to the model.

The classifier and the revision service both need structured JSON back from
Claude. They share the same client, the same model, the same fence-stripping,
and the same failure vocabulary so a generation failure is always reported the
same way rather than surfacing as a stray exception in the interface.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from src.common import ROOT, BettyOSError

MODEL = "claude-sonnet-4-6"


class GenerationError(BettyOSError):
    """The model could not be reached, or did not return usable structure."""


def api_key(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    load_dotenv(ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise GenerationError(
            "No API key configured, so BettyOS cannot generate suggestions.",
            hint="Add ANTHROPIC_API_KEY to the .env file in the project folder.",
        )
    return key


def api_key_present() -> bool:
    try:
        api_key()
        return True
    except GenerationError:
        return False


def extract_json(text: str) -> Any:
    """Parse a JSON object or array out of a model reply."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise GenerationError(
        "The model reply could not be read as structured data.",
        hint="Try generating again.",
    )


def complete_json(
    prompt: str,
    *,
    key: str | None = None,
    max_tokens: int = 3000,
    temperature: float | None = None,
) -> Any:
    """Send one prompt, return parsed JSON. Every failure becomes GenerationError."""
    import anthropic

    resolved = api_key(key)
    try:
        client = anthropic.Anthropic(api_key=resolved)
        request: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            request["temperature"] = temperature
        response = client.messages.create(**request)
    except GenerationError:
        raise
    except Exception as exc:  # noqa: BLE001 — network and API errors both land here
        raise GenerationError(
            f"BettyOS could not reach the language model: {exc}",
            hint="Check the connection and the API key, then try again.",
        ) from exc

    chunks = [getattr(block, "text", "") or "" for block in response.content]
    raw = "\n".join(chunk for chunk in chunks if chunk).strip()
    if not raw:
        raise GenerationError("The model returned an empty reply.", hint="Try again.")
    return extract_json(raw)
