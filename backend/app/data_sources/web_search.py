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


def niche_queries(
    product_name: str,
    extra: str | None = None,
    max_queries: int | None = None,
    category: str | None = None,
) -> list[str]:
    """Build search queries. Food recalls get pathogen/outbreak queries; physical products only when searched."""
    is_food = (category or "").lower() in {"food", "beverage", "produce", "dairy"} or _looks_like_food(
        product_name, extra
    )
    if is_food:
        # Unofficial: iWasPoisoned + grocery/illness first; Reddit is supplementary.
        base = [
            f'site:iwaspoisoned.com {product_name}',
            f'site:iwaspoisoned.com {product_name} (grocery OR restaurant OR brand OR sick)',
            f'{product_name} site:iwaspoisoned.com (vomiting OR diarrhea OR "food poisoning")',
            f'{product_name} ("food poisoning" OR "got sick" OR vomiting) (grocery OR Costco OR Walmart) -site:fda.gov -site:cdc.gov',
            f'{product_name} site:reddit.com (sick OR vomiting OR diarrhea OR "food poisoning" OR nauseous)',
        ]
    else:
        # Physical / appliance queries — only used when a specific non-food product is searched.
        base = [
            f'"{product_name}" site:reddit.com overheating OR "burning smell" OR problem',
            f'"{product_name}" overheating OR "burning smell" OR "burning plastic"',
            f'"{product_name}" recall OR "caught fire" OR smoke -site:cpsc.gov',
            f'"{product_name}" "stopped working" OR shutdown OR dangerous',
        ]
    if extra:
        base.insert(0, f"{product_name} {extra}")
    if max_queries is not None:
        return base[: max(1, max_queries)]
    return base


def _looks_like_food(product_name: str, extra: str | None) -> bool:
    text = f"{product_name} {extra or ''}".lower()
    needles = (
        "lettuce",
        "romaine",
        "spinach",
        "cheese",
        "milk",
        "yogurt",
        "chicken",
        "beef",
        "fish",
        "salmon",
        "ice cream",
        "chocolate",
        "snack",
        "chips",
        "sauce",
        "soup",
        "bread",
        "egg",
        "produce",
        "food",
        "cyclospora",
        "listeria",
        "salmonella",
    )
    return any(n in text for n in needles)


def search_web(queries: list[str], limit_per_query: int = 5) -> list[SearchHit]:
    """
    One search backend, no site-specific APIs.
    Preference order: Exa → Brave → Gemini → OpenAI (Exa first for niche semantic search).
    Falls through when a configured provider errors or returns no hits.
    """
    settings = get_settings()
    providers = []
    if settings.exa_api_key:
        providers.append(("exa", lambda: _exa_search(queries, settings, limit_per_query)))
    if settings.brave_search_api_key:
        providers.append(("brave", lambda: _brave_search(queries, settings, limit_per_query)))
    if settings.gemini_api_key:
        providers.append(("gemini", lambda: _gemini_search(queries, settings)))
    if settings.openai_api_key:
        providers.append(("openai", lambda: _openai_search(queries, settings)))

    for name, runner in providers:
        try:
            hits = runner()
        except Exception:
            continue
        if hits:
            return _dedupe_hits(hits)
    return []


def available_provider() -> str | None:
    settings = get_settings()
    if settings.exa_api_key:
        return "exa"
    if settings.brave_search_api_key:
        return "brave"
    if settings.gemini_api_key:
        return "gemini"
    if settings.openai_api_key:
        return "openai"
    return None

def _openai_search(queries: list[str], settings) -> list[SearchHit]:
    from ..openai_http import openai_post

    prompt = (
        "Search the public web for first-person reports, forum threads, news, or official notices "
        "about problems with these queries:\n"
        + "\n".join(f"- {query}" for query in queries)
        + "\nReturn a JSON list of objects with keys title, url, snippet. "
        "Only include real http(s) pages. Prefer consumer reports and recall notices."
    )
    data = openai_post(
        "/v1/responses",
        settings.openai_api_key,
        {
            "model": settings.openai_search_model,
            "tools": [{"type": "web_search"}],
            "tool_choice": {"type": "web_search"},
            "include": ["web_search_call.action.sources"],
            "input": prompt,
        },
        timeout=60,
    )
    hits: list[SearchHit] = []
    query = queries[0] if queries else "product safety"
    for item in data.get("output") or []:
        if item.get("type") == "web_search_call":
            action = item.get("action") or {}
            for source in action.get("sources") or []:
                url = source.get("url")
                if url:
                    hits.append(SearchHit(title=url, url=url, snippet="", provider="openai", query=query))
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            for annotation in content.get("annotations") or []:
                if annotation.get("type") == "url_citation" and annotation.get("url"):
                    hits.append(
                        SearchHit(
                            title=annotation.get("title") or annotation["url"],
                            url=annotation["url"],
                            snippet="",
                            provider="openai",
                            query=query,
                        )
                    )
            for match in _json_objects(content.get("text") or ""):
                if match.get("url"):
                    hits.append(
                        SearchHit(
                            title=match.get("title") or match["url"],
                            url=match["url"],
                            snippet=match.get("snippet") or "",
                            provider="openai",
                            query=query,
                        )
                    )
    return [hit for hit in hits if hit.url.startswith(("http://", "https://"))]


def _gemini_search(queries: list[str], settings) -> list[SearchHit]:
    import httpx
    import time

    hits: list[SearchHit] = []
    for index, query in enumerate(queries):
        if index:
            time.sleep(2)  # be gentle on free-tier RPM
        prompt = (
            "Find recent public web pages where people report problems with this query. "
            "Return a JSON list of {title, url, snippet}. Only include pages that actually exist. "
            f"Query: {query}"
        )
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
            },
            timeout=40,
        )
        if response.status_code == 429:
            # Don't burn retries on free tier — return whatever we have.
            break
        if response.status_code >= 400:
            detail = ""
            try:
                detail = (response.json().get("error") or {}).get("message") or ""
            except Exception:
                detail = response.text[:160]
            raise RuntimeError(f"Gemini search failed ({response.status_code}): {detail[:160]}")
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
    from datetime import datetime, timedelta, timezone

    start = (
        datetime.now(timezone.utc) - timedelta(days=max(1, settings.discovery_recency_days))
    ).strftime("%Y-%m-%dT00:00:00.000Z")

    preferred_domains = [
        "reddit.com",
        "iwaspoisoned.com",
        "facebook.com",
        "nextdoor.com",
    ]

    hits: list[SearchHit] = []
    for query in queries:
        payloads = [
            {
                "query": query,
                "numResults": limit,
                "type": "auto",
                "contents": {"text": False},
                "startPublishedDate": start,
                "includeDomains": preferred_domains,
            },
            {
                "query": query,
                "numResults": limit,
                "type": "auto",
                "contents": {"text": False},
                "startPublishedDate": start,
            },
        ]
        # Query already pins a site — skip the includeDomains pass.
        if "site:" in query.lower():
            payloads = payloads[1:]
        for payload in payloads:
            try:
                response = httpx.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": settings.exa_api_key},
                    json=payload,
                    timeout=25,
                )
                response.raise_for_status()
            except Exception:
                continue
            batch = response.json().get("results", [])
            for item in batch:
                hits.append(
                    SearchHit(
                        title=item.get("title") or item.get("url"),
                        url=item["url"],
                        snippet=(item.get("text") or "")[:280],
                        provider="exa",
                        query=query,
                    )
                )
            if batch:
                break
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
