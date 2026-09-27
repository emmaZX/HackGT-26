"""
openFDA CAERS / food adverse event connector.

Pulls recent food/event reports, normalizes product keys, and leaves spike
math to pipeline.spikes (no LLM here).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

CAERS_ENDPOINT = "https://api.fda.gov/food/event.json"


def fetch_recent_events(
    *,
    lookback_days: int = 90,
    fetch_limit: int = 3000,
) -> list[dict]:
    """
    Return normalized CAERS events:
      report_number, date, brand, name, reactions, source_url, raw_product
    """
    end = datetime.utcnow()
    # CAERS date_started often lags; widen automatically if the short window is empty.
    windows = [
        max(7, lookback_days),
        max(lookback_days, 270),
        400,
    ]
    searches: list[str] = []
    for days in windows:
        start = end - timedelta(days=days)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        searches.append(f"date_started:[{s} TO {e}]")
        searches.append(f"date_created:[{s} TO {e}]")

    raw_rows: list[dict] = []
    with httpx.Client(timeout=45, follow_redirects=True, trust_env=False) as client:
        for search in searches:
            raw_rows = _paginate(client, search, fetch_limit)
            if raw_rows:
                logger.info("CAERS search hit via %s (%s rows)", search, len(raw_rows))
                break
        if not raw_rows:
            raw_rows = _paginate(client, None, min(fetch_limit, 1000))

    logger.info("CAERS fetched %s raw events (lookback=%sd)", len(raw_rows), lookback_days)
    normalized: list[dict] = []
    for row in raw_rows:
        for item in _normalize_event(row):
            normalized.append(item)
    return normalized


def _paginate(client: httpx.Client, search: str | None, fetch_limit: int) -> list[dict]:
    raw_rows: list[dict] = []
    skip = 0
    page = min(1000, max(100, fetch_limit))
    while len(raw_rows) < fetch_limit:
        params: dict = {
            "limit": min(page, fetch_limit - len(raw_rows)),
            "skip": skip,
        }
        if search:
            params["search"] = search
        try:
            response = client.get(CAERS_ENDPOINT, params=params)
            if response.status_code == 404:
                # openFDA uses 404 for zero results.
                break
            if response.status_code >= 400:
                logger.warning("CAERS HTTP %s at skip=%s search=%s", response.status_code, skip, search)
                break
            payload = response.json()
            batch = payload.get("results") or []
            if not batch:
                break
            raw_rows.extend(batch)
            total = (payload.get("meta") or {}).get("results", {}).get("total")
            skip += len(batch)
            if total is not None and skip >= int(total):
                break
            if len(batch) < page:
                break
        except Exception:
            logger.exception("CAERS fetch failed at skip=%s", skip)
            break
    return raw_rows


def _normalize_event(row: dict) -> list[dict]:
    report_number = str(row.get("report_number") or "").strip()
    if not report_number:
        return []
    date = _parse_date(row.get("date_started") or row.get("date_created"))
    if not date:
        return []
    reactions = [str(r).strip() for r in (row.get("reactions") or []) if str(r).strip()]
    products = row.get("products") or []
    source_url = (
        f"{CAERS_ENDPOINT}?search=report_number:{quote(report_number)}&limit=1"
    )
    out: list[dict] = []
    for product in products:
        role = str(product.get("role") or "").upper()
        if role and role not in {"SUSPECT", "CONCOMITANT", ""}:
            # Keep suspect + unlabeled; skip pure concomitant noise when labeled.
            if role == "CONCOMITANT":
                continue
        brand_name = str(product.get("name_brand") or "").strip()
        generic = str(product.get("name_generic") or "").strip()
        label = brand_name or generic
        if not label or len(label) < 3:
            continue
        # Skip FOIA redaction / non-product CAERS noise.
        if re.search(r"\bexemption\s*4\b", label, re.I) or label.upper() in {"NONE", "UNKNOWN", "N/A"}:
            continue
        brand, name = _split_brand_name(label)
        industry = str(product.get("industry_name") or "").strip()
        out.append(
            {
                "report_number": report_number,
                "date": date,
                "brand": brand,
                "name": name,
                "label": label,
                "reactions": reactions,
                "industry": industry,
                "source_url": source_url,
                "raw_product": label,
            }
        )
    return out


def _split_brand_name(label: str) -> tuple[str, str]:
    from ..pipeline.product_identity import simplify_food_item

    text = re.sub(r"\s+", " ", label).strip()
    lowered = text.lower()
    two_word = (
        ("great value ", "Great Value"),
        ("friendly farms ", "Friendly Farms"),
        ("fresh express ", "Fresh Express"),
        ("trader joe's ", "Trader Joe's"),
        ("trader joes ", "Trader Joe's"),
        ("hellofresh ", "HelloFresh"),
        ("hello fresh ", "HelloFresh"),
        ("premier protein ", "Premier Protein"),
    )
    for prefix, brand in two_word:
        if lowered.startswith(prefix):
            rest = text[len(prefix) :].strip()
            simplified = simplify_food_item(brand=brand, name=rest.title() if rest else brand)
            return simplified["brand"][:120], simplified["name"][:180]

    parts = text.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) >= 2:
        simplified = simplify_food_item(
            brand=parts[0].title(),
            name=parts[1].title(),
            fallback=text.title()[:72],
        )
        return simplified["brand"][:120], simplified["name"][:180]
    simplified = simplify_food_item(brand="Unknown", name=text.title(), fallback="Food item")
    return simplified["brand"][:120], simplified["name"][:180]


def _parse_date(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    # openFDA often uses YYYYMMDD
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d")
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10].replace("-", "") if fmt == "%Y%m%d" else text[:10], fmt)
        except ValueError:
            continue
    return None


def product_key(brand: str, name: str) -> str:
    blob = f"{brand} {name}".lower()
    blob = re.sub(r"[^a-z0-9]+", "-", blob).strip("-")
    return blob[:72] or "caers-product"
