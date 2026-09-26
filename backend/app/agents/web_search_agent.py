"""Agent 2 — Live niche web search (Exa-first browsing tool)."""

from __future__ import annotations

from ..data_sources.web_search import SearchHit, available_provider, search_web


def search_niche(queries: list[str], limit_per_query: int = 5) -> tuple[str | None, list[SearchHit]]:
    """Execute agent-written queries through the configured search backend."""
    provider = available_provider()
    if not provider:
        return None, []
    hits = search_web(queries, limit_per_query=limit_per_query)
    return provider, hits
