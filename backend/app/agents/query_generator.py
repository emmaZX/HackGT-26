"""Agent 1 — Autonomous query generator for niche complaint searches."""

from __future__ import annotations

import json
import re

from ..config import get_settings
from ..data_sources.web_search import niche_queries


def generate_queries(
    *,
    brand: str,
    name: str,
    category: str | None,
    extra: str | None = None,
    recall_hint: dict | None = None,
    max_queries: int | None = None,
) -> list[str]:
    """
    Build hyper-niche search strings aimed at human complaints.

    Prefer Gemini when available; always merge with template seeds so Exa
    still gets Reddit / illness oriented queries if the LLM is unavailable.
    """
    product = f"{brand} {name}".strip()
    seeds = niche_queries(product, extra, max_queries=None, category=category)
    dynamic = _llm_queries(product, category, extra, recall_hint) or _heuristic_queries(
        product, category, extra, recall_hint
    )
    # Dynamic first (more specific), then seeds — then de-dupe.
    merged: list[str] = []
    seen: set[str] = set()
    for query in dynamic + seeds:
        key = re.sub(r"\s+", " ", query.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(query.strip())
    if max_queries is not None:
        return merged[: max(1, max_queries)]
    return merged[:8]


def _heuristic_queries(
    product: str,
    category: str | None,
    extra: str | None,
    recall_hint: dict | None,
) -> list[str]:
    from datetime import datetime

    year = datetime.utcnow().year
    illness = '("threw up" OR vomiting OR diarrhea OR "food poisoning" OR "got sick" OR nauseous)'
    batch = '(lot OR batch OR "use by" OR "best by" OR "sell by")'
    recent = f"({year} OR \"this week\" OR \"last month\" OR recently OR today)"
    # Primary unofficial path: iWasPoisoned / grocery illness chatter — not category watches.
    queries = [
        f'site:iwaspoisoned.com {product}',
        f'site:iwaspoisoned.com {product} (grocery OR sick OR restaurant)',
        f'{product} {illness} (grocery OR Costco OR Walmart OR "food poisoning") {recent} -site:fda.gov',
        f'{product} {illness} (family OR "my kids" OR "three people" OR household) {recent}',
        f'{product} {batch} {illness} site:iwaspoisoned.com',
        f'"{product}" ("taste weird" OR "smell weird" OR "off smell") (sick OR vomiting) {recent}',
    ]
    if recall_hint:
        hazard = (recall_hint.get("hazard") or "").split()[0:3]
        if hazard:
            queries.insert(
                0,
                f'{product} {" ".join(hazard)} site:iwaspoisoned.com OR site:reddit.com sick OR illness {recent}',
            )
    else:
        queries = [q for q in queries if " recall " not in f" {q.lower()} "]
    if extra:
        queries.insert(0, f"{product} {extra} site:iwaspoisoned.com {recent}")
    if (category or "").lower() == "food":
        queries.append(f'{product} site:iwaspoisoned.com ("1 star" OR sick OR vomiting) {recent}')
    return queries


def _llm_queries(
    product: str,
    category: str | None,
    extra: str | None,
    recall_hint: dict | None,
) -> list[str]:
    settings = get_settings()
    if not settings.gemini_api_key:
        return []
    try:
        import httpx
    except Exception:
        return []

    context = {
        "product": product,
        "category": category,
        "extra": extra,
        "recall": recall_hint,
    }
    prompt = (
        "You are the Query Generator agent for Recall Me Maybe. "
        "Write 4-6 hyper-specific web search queries to find RECENT first-person consumer complaints "
        "on Reddit, iwaspoisoned.com, Facebook groups, Nextdoor, Discord, TikTok comments — "
        "NOT FDA/CDC pages, not press releases, not year-old blogs. "
        "Prefer illness language (vomiting, diarrhea, food poisoning, batch/lot, multiple people). "
        f"Bias toward the last {get_settings().discovery_recency_days} days / this year only. "
        "Include site:reddit.com or site:iwaspoisoned.com in most queries. "
        "Avoid the word 'recall' unless the product is already under an Ongoing notice. "
        "Return ONLY a JSON list of strings.\n\n"
        f"Context: {json.dumps(context)[:1200]}"
    )
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=25,
        )
        if response.status_code >= 400:
            return []
        text = ""
        for candidate in response.json().get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text") or ""
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        parsed = json.loads(match.group(0))
        return [str(item).strip() for item in parsed if str(item).strip()][:6]
    except Exception:
        return []
