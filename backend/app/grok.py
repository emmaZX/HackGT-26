"""
Minimal Grok (xAI) client for the Responses API.

Env (backend/.env or the root .env):
  XAI_API_KEY  your xAI key (console.x.ai → API Keys)
  XAI_MODEL           optional; defaults to grok-4.7. A "fast" variant is much cheaper;
                      check console.x.ai for current names.
  XAI_MAX_TOOL_CALLS  optional; caps searches per request (default 3). Each X search call is
                      billed, so this is the main cost control.
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


class GrokError(RuntimeError):
    pass


def api_key() -> str:
    key = os.getenv("XAI_API_KEY", "").strip()
    if not key:
        raise GrokError("XAI_API_KEY is not set in backend/.env")
    return key


def respond(prompt: str, tools: list[dict] | None = None, timeout: float = 180.0) -> dict:
    """One Responses API call. Server-side tools (x_search, web_search) run on xAI's side."""
    payload: dict = {
        "model": os.getenv("XAI_MODEL", DEFAULT_MODEL),
        "input": [{"role": "user", "content": prompt}],
        # Keep "[[1]](url)" markers out of the text so JSON answers stay parseable
        "include": ["no_inline_citations"],
    }
    if tools:
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
