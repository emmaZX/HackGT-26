"""
Minimal Grok (xAI) client for the Responses API.

Env (backend/.env or the root .env):
  XAI_API_KEY  your xAI key (console.x.ai → API Keys)
  XAI_MODEL           optional; defaults to grok-4.7. A "fast" variant is much cheaper;
                      check console.x.ai for current names.
  XAI_MAX_TOOL_CALLS  optional; caps searches per request (default 3). Each X search call is
                      billed, so this is the main cost control.
  XAI_TEXT_MODEL      optional; model for plain text jobs (extraction, triage, summaries).
                      Defaults to the cheaper grok-4.20-0309-non-reasoning.
  XAI_PIPELINE        set to 0 to stop pipeline steps (triage, extraction, naming, summaries,
                      queries) from calling Grok; X search is unaffected.
  XAI_WEB_SEARCH      set to 1 to let web discovery use Grok's web_search tool (off by default,
                      because searches can trigger it and each call costs credit).
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND / ".env")
load_dotenv(_BACKEND.parent / ".env")

XAI_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = "grok-4.7"
DEFAULT_TEXT_MODEL = "grok-4.20-0309-non-reasoning"


class GrokError(RuntimeError):
    pass


def api_key() -> str:
    key = os.getenv("XAI_API_KEY", "").strip()
    if not key:
        raise GrokError("XAI_API_KEY is not set in backend/.env")
    return key


def respond(prompt: str, tools: list[dict] | None = None, timeout: float = 180.0, model: str | None = None) -> dict:
    """One Responses API call. Server-side tools (x_search, web_search) run on xAI's side."""
    payload: dict = {
        "model": model or os.getenv("XAI_MODEL", DEFAULT_MODEL),
        "input": [{"role": "user", "content": prompt}],
    }
    if tools:
        # Keep "[[1]](url)" markers out of the text so JSON answers stay parseable
        payload["include"] = ["no_inline_citations"]
        payload["tools"] = tools
        payload["max_tool_calls"] = int(os.getenv("XAI_MAX_TOOL_CALLS", "3") or 3)
    response = httpx.post(
        XAI_URL,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise GrokError(f"xAI API {response.status_code}: {response.text[:300]}")
    return response.json()


def output_text(response: dict) -> str:
    """All text the model wrote, joined."""
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts: list[str] = []
    for item in response.get("output") or []:
        for block in item.get("content") or []:
            if block.get("type") in ("output_text", "text") and block.get("text"):
                parts.append(block["text"])
    return "\n".join(parts)


def cited_urls(response: dict) -> set[str]:
    """Every source URL the search tools actually returned (used to reject invented links)."""
    urls: set[str] = set()
    for c in response.get("citations") or []:
        url = c if isinstance(c, str) else (c.get("url") if isinstance(c, dict) else None)
        if url:
            urls.add(url)
    for item in response.get("output") or []:
        for block in item.get("content") or []:
            for ann in block.get("annotations") or []:
                if ann.get("url"):
                    urls.add(ann["url"])
    return urls


# ---------------------------------------------------------------------------
# Plain text jobs for the pipeline (extraction, triage, naming, summaries, queries)
# ---------------------------------------------------------------------------


def grok_available() -> bool:
    """True when pipeline AI steps should use Grok. Set XAI_PIPELINE=0 to turn them off (saves credit)."""
    return bool(os.getenv("XAI_API_KEY", "").strip()) and os.getenv("XAI_PIPELINE", "1").strip() != "0"


def ai_method() -> str:
    """Which engine ai_text() will use, recorded on results as their method."""
    return "grok" if grok_available() else "gemini"


def ai_text(prompt: str, timeout: float = 30.0) -> str | None:
    """
    Run a plain text prompt. Grok when XAI_API_KEY is set, otherwise Gemini if configured.
    Returns None on any failure so callers fall back to their non-AI rules.
    """
    if grok_available():
        try:
            response = respond(prompt, timeout=timeout, model=os.getenv("XAI_TEXT_MODEL", DEFAULT_TEXT_MODEL))
            return output_text(response) or None
        except Exception:
            return None
    try:
        from .config import get_settings

        settings = get_settings()
        if not settings.gemini_api_key:
            return None
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=timeout,
        )
        if response.status_code >= 400:
            return None
        text = ""
        for candidate in response.json().get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text") or ""
        return text or None
    except Exception:
        return None
