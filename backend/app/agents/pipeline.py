"""Orchestrate the five discovery agents end-to-end."""

from __future__ import annotations

from ..config import get_settings
from ..data_sources.page_fetch import domain_of
from ..models import Product, Recall
from .geo_agent import correlate_location
from .page_fetch_agent import fetch_candidates
from .query_generator import generate_queries
from .triage_agent import is_recall_coverage, should_ingest_as_internet_evidence, triage_complaint
from .web_search_agent import search_niche


def run_agent_pipeline(
    *,
    product: Product,
    extra: str | None,
    max_pages: int,
    max_queries: int | None,
    already_ingested,
    is_ingestible,
    is_agency,
    rank_url,
    official_recall: Recall | None = None,
) -> dict:
    """
    Returns:
      provider, queries, hits, candidates (first-person pages to ingest),
      recall_coverage (pages that should trigger openFDA confirm), notes, agent_log
    """
    recall_hint = None
    has_official = official_recall is not None
    if official_recall:
        recall_hint = {
            "agency": official_recall.agency,
            "hazard": official_recall.hazard,
            "reason": official_recall.reason,
        }

    # 1) Query Generator
    queries = generate_queries(
        brand=product.brand,
        name=product.name,
        category=product.category,
        extra=extra,
        recall_hint=recall_hint,
        max_queries=max_queries,
    )
    agent_log = [{"agent": "query_generator", "queries": queries}]

    # 2) Web Search (Exa / Brave / Gemini)
    provider, hits = search_niche(queries, limit_per_query=5)
    agent_log.append({"agent": "web_search", "provider": provider, "hit_count": len(hits)})

    if not provider:
        return {
            "provider": None,
            "queries": queries,
            "hits": [],
            "candidates": [],
            "recall_coverage": [],
            "notes": ["no search provider"],
            "agent_log": agent_log,
        }

    # 3) Page Fetch — human sources only
    def skip_url(url: str) -> bool:
        return already_ingested(url) or is_agency(url)

    fetch_budget = max(max_pages * 3, max_pages + 4)
    pages = fetch_candidates(
        hits,
        limit=fetch_budget,
        skip_url=skip_url,
        rank_url=rank_url,
        is_ingestible=is_ingestible,
        is_agency=is_agency,
    )
    agent_log.append({"agent": "page_fetch", "fetched": len(pages)})

    # 4 + 5) Triage + Geo
    settings = get_settings()
    notes: list[str] = []
    candidates: list[dict] = []
    coverage: list[dict] = []
    product_hint = f"{product.brand} {product.name}"
    for item in pages:
        verdict = triage_complaint(
            text=item["text"],
            title=item.get("title"),
            product_hint=product_hint,
            url=item.get("final_url"),
            has_official_recall=has_official,
            recency_days=settings.discovery_recency_days,
        )
        if is_recall_coverage(verdict):
            coverage.append({**item, "triage": verdict})
            notes.append(f"coverage {item.get('final_url')}: {verdict.get('reason', '')[:80]}")
            continue
        if not should_ingest_as_internet_evidence(verdict, has_official_recall=has_official):
            notes.append(
                f"reject {item.get('final_url')}: {verdict.get('label')} "
                f"({verdict.get('reason', '')[:80]})"
            )
            continue
        if len(candidates) >= max_pages:
            continue
        geo = correlate_location(item["text"], item.get("title"))
        candidates.append(
            {
                **item,
                "triage": verdict,
                "geo": geo,
                "host": item.get("host") or domain_of(item.get("final_url") or ""),
            }
        )

    agent_log.append(
        {
            "agent": "triage",
            "kept": len(candidates),
            "coverage": len(coverage),
            "rejected": len(pages) - len(candidates) - len(coverage),
        }
    )
    agent_log.append(
        {"agent": "geo_correlate", "located": sum(1 for c in candidates if c["geo"].get("location_label"))}
    )

    return {
        "provider": provider,
        "queries": queries,
        "hits": hits,
        "candidates": candidates,
        "recall_coverage": coverage,
        "notes": notes,
        "agent_log": agent_log,
    }
