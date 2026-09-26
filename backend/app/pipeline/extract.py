from __future__ import annotations

import json
import re

from ..config import get_settings
from ..security import sanitize_text

ISSUE_PATTERNS: list[tuple[str, str, list[str]]] = [
    ("overheating", "possible overheating", ["overheat", "too hot", "burning hot", "hot to the touch", "heat up"]),
    ("burning odor", "possible overheating", ["burning smell", "smells like burning", "burning plastic", "acrid", "electrical fire smell"]),
    ("smoke", "possible fire risk", ["smoke", "smoking", "smolder"]),
    ("unexpected shutdown", "unexpected power loss", ["shut off", "shutdown", "powered down", "died randomly", "turns itself off"]),
    ("battery swelling", "battery issue", ["swollen", "battery bulge", "puffed battery"]),
    ("skin irritation", "skin reaction", ["rash", "irritat", "itchy", "broke out", "redness"]),
    ("choking hazard", "physical hazard", ["choking", "small part", "broke off", "swallowed"]),
    ("shock", "electrical", ["shocked", "electric shock", "sparked", "spark"]),
    ("leak", "containment failure", ["leak", "leaking", "spilled"]),
    ("fire", "possible fire risk", ["caught fire", "on fire", "flames"]),
]


def extract_report(text: str, product_hint: str | None = None) -> dict:
    """
    Identify what the report says. Do not diagnose people, infer medical
    conditions, or assert that the product caused harm.
    """
    cleaned = sanitize_text(text, 4000)
    settings = get_settings()
    if settings.gemini_api_key:
        try:
            return _gemini_extract(cleaned, product_hint, settings.gemini_api_key, settings.gemini_model)
        except Exception:
            pass
    return _heuristic_extract(cleaned, product_hint)


def _heuristic_extract(text: str, product_hint: str | None) -> dict:
    lowered = text.lower()
    issues: list[dict] = []
    for name, category, needles in ISSUE_PATTERNS:
        if any(needle in lowered for needle in needles):
            issues.append({"issue": name, "category": category, "confidence": 0.72})
    if not issues:
        issues.append({"issue": "unspecified issue", "category": "community report", "confidence": 0.4})
    return {
        "product": product_hint,
        "issues": issues,
        "severity": "as described by the reporter",
        "location": None,
        "summary": text[:240],
        "method": "heuristic",
    }


def _gemini_extract(text: str, product_hint: str | None, api_key: str, model: str) -> dict:
    import httpx

    prompt = (
        "Extract only what the following consumer product report literally says. "
        "Do not diagnose people. Do not infer medical conditions. Do not assert causality. "
        "Return JSON with keys product, issues (list of {issue, category, confidence}), "
        "severity (quote or 'as described by the reporter'), location, summary. "
        f"Known product hint: {product_hint or 'unknown'}\n\nREPORT:\n{text}"
    )
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
    )
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    match = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(match.group(0) if match else raw)
    data["method"] = "gemini"
    return data
