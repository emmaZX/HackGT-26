"""Agent 3 — Fetch readable page content for candidate complaint URLs."""

from __future__ import annotations

from ..data_sources.page_fetch import domain_of, fetch_readable
from ..data_sources.web_search import SearchHit


def fetch_candidates(
    hits: list[SearchHit],
    *,
    limit: int,
    skip_url,
    rank_url,
    is_ingestible,
    is_agency,
) -> list[dict]:
    """
    Pull page text for the best human-sourced hits.
    Returns dicts: {hit, page, final_url, host}.
    """
    ordered = sorted(hits, key=lambda h: rank_url(h.url))
    pages: list[dict] = []
    for hit in ordered:
        if len(pages) >= limit:
            break
        if not is_ingestible(hit.url) or is_agency(hit.url):
            continue
        if skip_url(hit.url):
            continue
        try:
            page = fetch_readable(hit.url)
        except Exception:
            continue
        final_url = page.get("url") or hit.url
        if not is_ingestible(final_url) or is_agency(final_url):
            continue
        text = page.get("text") or ""
        if len(text) < 40:
            continue
        pages.append(
            {
                "hit": hit,
                "page": page,
                "final_url": final_url,
                "host": domain_of(final_url),
                "text": text,
                "title": page.get("title") or hit.title,
                "snippet": hit.snippet or text[:220],
            }
        )
    return pages
