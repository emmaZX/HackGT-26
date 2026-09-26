from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str
    query: str


def niche_queries(product_name: str, extra: str | None = None, max_queries: int | None = None) -> list[str]:
    base = [
        f'"{product_name}" overheating OR "burning smell" OR "burning plastic"',
        f'"{product_name}" recall OR "caught fire" OR smoke',
        f'"{product_name}" "stopped working" OR shutdown OR "turned itself off"',
        f"{product_name} site:reddit.com problem OR issue OR dangerous",
    ]
    if extra:
        base.insert(0, f"{product_name} {extra}")
    if max_queries is not None:
        return base[: max(1, max_queries)]
    return base


def search_web(queries: list[str], limit_per_query: int = 5) -> list[SearchHit]:
    """
    One search backend, no site-specific APIs.
    Preference order: Gemini grounding → Exa → Brave.
    Prefer Brave when only a Brave key is set; Gemini still wins if configured.
    """
    settings = get_settings()
    hits: list[SearchHit] = []
    if settings.gemini_api_key:
        hits = _gemini_search(queries, settings)
    elif settings.exa_api_key:
        hits = _exa_search(queries, settings, limit_per_query)
    elif settings.brave_search_api_key:
        hits = _brave_search(queries, settings, limit_per_query)
    return _dedupe_hits(hits)


def available_provider() -> str | None:
    settings = get_settings()
    if settings.gemini_api_key:
        return "gemini"
    if settings.exa_api_key:
        return "exa"
    if settings.brave_search_api_key:
        return "brave"
    return None


def _gemini_search(queries: list[str], settings) -> list[SearchHit]:
    import httpx

    hits: list[SearchHit] = []
    for query in queries:
        prompt = (
            "Find recent public web pages where people report problems with this query. "
            "Return a JSON list of {title, url, snippet}. Only include pages that actually exist. "
            f"Query: {query}"
        )
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            params={"key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
            },
            timeout=40,
        )
        response.raise_for_status()
        data = response.json()
        for candidate in data.get("candidates", []):
            grounding = candidate.get("groundingMetadata", {})
            for chunk in grounding.get("groundingChunks", []):
                web = chunk.get("web") or {}
                if web.get("uri"):
                    hits.append(
                        SearchHit(
                            title=web.get("title") or web["uri"],
                            url=web["uri"],
                            snippet="",
                            provider="gemini",
                            query=query,
                        )
                    )
            text = ""
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text") or ""
            for match in _json_objects(text):
                if match.get("url"):
                    hits.append(
                        SearchHit(
                            title=match.get("title") or match["url"],
                            url=match["url"],
                            snippet=match.get("snippet") or "",
                            provider="gemini",
                            query=query,
                        )
                    )
    return hits


def _exa_search(queries: list[str], settings, limit: int) -> list[SearchHit]:
    import httpx

    hits: list[SearchHit] = []
    for query in queries:
        response = httpx.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": settings.exa_api_key},
            json={"query": query, "numResults": limit, "type": "auto", "contents": {"text": False}},
            timeout=25,
        )
        response.raise_for_status()
        for item in response.json().get("results", []):
            hits.append(
                SearchHit(
                    title=item.get("title") or item.get("url"),
                    url=item["url"],
                    snippet=(item.get("text") or "")[:280],
                    provider="exa",
                    query=query,
                )
            )
    return hits


def _brave_search(queries: list[str], settings, limit: int) -> list[SearchHit]:
    import httpx

    hits: list[SearchHit] = []
    for query in queries:
        response = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": settings.brave_search_api_key, "Accept": "application/json"},
            params={"q": query, "count": limit},
            timeout=20,
        )
        response.raise_for_status()
        for item in response.json().get("web", {}).get("results", []):
            hits.append(
                SearchHit(
                    title=item.get("title") or item.get("url"),
                    url=item["url"],
                    snippet=item.get("description") or "",
                    provider="brave",
                    query=query,
                )
            )
    return hits


def _dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        key = hit.url.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _json_objects(text: str) -> list[dict]:
    import json
    import re

    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]
