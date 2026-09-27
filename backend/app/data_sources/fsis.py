"""
USDA-FSIS meat/poultry recall connector.

Prefer the live FSIS JSON API. Some networks get Akamai 403; fall back to the
latest Internet Archive snapshot of the same endpoint so demos stay honest.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from html import unescape

import httpx

logger = logging.getLogger(__name__)

FSIS_API = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.fsis.usda.gov/",
}


def fetch_active_recalls(limit: int = 40, max_age_days: int = 120) -> list[dict]:
    """Return normalized *recent* active FSIS recalls (same shape as FDA overlay items)."""
    rows = _load_raw_rows()
    if not rows:
        return []

    cutoff = datetime.utcnow() - timedelta(days=max(14, max_age_days))
    active: list[dict] = []
    for row in rows:
        if not _is_active(row):
            continue
        item = _normalize(row)
        if not item:
            continue
        # Drop resolved / ancient PHAs — home should only show still-relevant notices.
        if item["recall_date"] < cutoff:
            continue
        active.append(item)

    # Newest first; outbreak-related floats up within the same day.
    active.sort(
        key=lambda item: (
            -(item["recall_date"].timestamp() if item.get("recall_date") else 0),
            0 if item.get("outbreak_related") else 1,
        )
    )
    return active[: max(1, limit)]


def _load_raw_rows() -> list[dict]:
    with httpx.Client(timeout=120, follow_redirects=True, trust_env=False, headers=_HEADERS) as client:
        try:
            response = client.get(FSIS_API, timeout=40)
            if response.status_code < 400:
                data = response.json()
                if isinstance(data, list) and data:
                    logger.info("FSIS live API returned %s rows", len(data))
                    return data
            logger.warning("FSIS live API status=%s — trying Wayback", response.status_code)
        except Exception:
            logger.exception("FSIS live API failed — trying Wayback")

        try:
            return _fetch_via_wayback(client)
        except Exception:
            logger.exception("FSIS Wayback fallback failed")
            return []


def _fetch_via_wayback(client: httpx.Client) -> list[dict]:
    cdx = client.get(
        WAYBACK_CDX,
        params={
            "url": "www.fsis.usda.gov/fsis/api/recall/v/1",
            "output": "json",
            "fl": "timestamp,statuscode",
            "filter": "statuscode:200",
            "fastLatest": "true",
            "limit": 8,
        },
        timeout=60,
    )
    cdx.raise_for_status()
    rows = cdx.json()
    timestamps: list[str] = []
    for row in rows[1:] if rows and isinstance(rows[0], list) else rows:
        if isinstance(row, list) and row:
            timestamps.append(str(row[0]))
    timestamps = sorted(set(timestamps), reverse=True)
    for ts in timestamps[:3]:
        url = f"https://web.archive.org/web/{ts}id_/{FSIS_API}"
        try:
            response = client.get(url, timeout=120)
        except Exception:
            logger.warning("FSIS Wayback snapshot %s timed out", ts)
            continue
        if response.status_code >= 400:
            continue
        data = response.json()
        if isinstance(data, list) and data:
            logger.info("FSIS Wayback %s returned %s rows", ts, len(data))
            return data
    return []


def _is_active(row: dict) -> bool:
    recall_type = str(row.get("field_recall_type") or "").lower()
    closed = str(row.get("field_closed_date") or "").strip()
    archived = row.get("field_archive_recall")
    active_notice = row.get("field_active_notice")

    if archived in (True, "True", "true", 1, "1"):
        return False
    if closed:
        return False
    if "active recall" in recall_type or recall_type.strip() == "active":
        return True
    if active_notice in (True, "True", "true", 1, "1"):
        return True
    if "recall" in recall_type and "inactive" not in recall_type and "closed" not in recall_type:
        return True
    # Recent public health alerts without a close date — still time-gated by max_age_days.
    if "alert" in recall_type and not closed:
        return True
    return False


def _normalize(row: dict) -> dict | None:
    title = _clean_text(row.get("field_title") or "")
    if not title:
        return None
    reason = _clean_text(row.get("field_recall_reason") or row.get("field_summary") or title)
    hazard = reason.split(".")[0][:180] or "FSIS hazard"
    recall_date = _parse_date(row.get("field_recall_date") or row.get("field_last_modified_date"))
    if not recall_date:
        return None

    url = str(row.get("field_recall_url") or "").strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if not url:
        number = str(row.get("field_recall_number") or "").strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
        url = f"https://www.fsis.usda.gov/recalls-alerts/{slug}" if slug else (
            f"https://www.fsis.usda.gov/recalls-alerts/{number}" if number else FSIS_API
        )

    brand, name = _brand_name(title, row.get("field_establishment") or "")
    # Drop import-violation legalese and other non-grocery titles.
    from ..pipeline.glance_titles import is_sensible_product, glance_title

    titled = glance_title(brand=brand, name=name)
    if not titled or not is_sensible_product(titled["brand"], titled["name"]):
        return None
    brand, name = titled["brand"], titled["name"]

    # Import / misbranding notices without a clear grocery item stay out of the shelf.
    reason_l = reason.lower()
    if any(
        x in reason_l
        for x in (
            "import violation",
            "without the benefit of inspection",
            "without benefit of inspection",
            "false usda",
            "misbranded",
        )
    ) and not re.search(
        r"\b(ground|chicken|turkey|beef|pork|sausage|deli|ham|nugget|bacon)\b",
        name,
        re.I,
    ):
        # Still allow clear proteins (Star Meat raw pork/beef/goat).
        if not re.search(r"\b(pork|beef|goat|chicken|turkey|meat)\b", f"{title} {name}", re.I):
            return None

    states = _clean_text(row.get("field_states") or "")
    nationwide = not states or "nationwide" in states.lower() or states.count(",") >= 8
    outbreak = row.get("field_related_to_outbreak") in (True, "True", "true", 1, "1")

    number = str(row.get("field_recall_number") or "").strip()
    slug_base = re.sub(r"[^a-z0-9]+", "-", f"{brand}-{name}-{number}".lower()).strip("-")[:72]

    return {
        "agency": "USDA-FSIS",
        "recall_date": recall_date,
        "reason": reason[:2000],
        "hazard": hazard,
        "source_url": url,
        "status": "Ongoing",
        "brand": brand[:120],
        "name": name[:180],
        "slug": f"fsis-{slug_base}" if slug_base else f"fsis-{number or 'recall'}",
        "nationwide": nationwide,
        "outbreak_related": outbreak,
        "recall_number": number,
        "summary": _strip_html(row.get("field_summary") or "")[:500],
    }


def _brand_name(title: str, establishment: str) -> tuple[str, str]:
    from ..pipeline.product_identity import simplify_food_item

    est = _clean_text(unescape(establishment or ""))
    simplified = simplify_food_item(brand=est, name=title, fallback="Meat / poultry")
    brand = simplified["brand"]
    name = simplified["name"]
    if brand in {"Unknown", "FDA watch"} and est:
        from ..pipeline.product_identity import _short_brand

        brand = _short_brand(est) or brand
    return brand[:120], name[:180]


def _parse_date(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _clean_text(value: str) -> str:
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    text = _strip_html(str(value or ""))
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", str(value or ""))
