"""
FDA Investigations of Foodborne Illness Outbreaks — active table rows.

Parses the public HTML table (including Not Yet Identified products).
Does not invent Recall rows — outbreak metadata rides on Product + Report.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html import unescape

import httpx

logger = logging.getLogger(__name__)

OUTBREAK_URL = (
    "https://www.fda.gov/food/outbreaks-foodborne-illness/"
    "investigations-foodborne-illness-outbreaks"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_active_outbreaks(limit: int = 25) -> list[dict]:
    """Return normalized active FDA outbreak investigation rows."""
    html = _fetch_html()
    if not html:
        return []
    rows = _parse_tables(html)
    active = [r for r in rows if _is_active(r)]
    # De-dupe by ref_id, keep first (current year table appears first).
    seen: set[str] = set()
    out: list[dict] = []
    for row in active:
        if row["ref_id"] in seen:
            continue
        seen.add(row["ref_id"])
        out.append(row)
        if len(out) >= limit:
            break
    logger.info("FDA outbreaks: %s active of %s parsed", len(out), len(rows))
    return out


def _fetch_html() -> str:
    try:
        with httpx.Client(timeout=40, follow_redirects=True, trust_env=False, headers=_HEADERS) as client:
            response = client.get(OUTBREAK_URL)
            response.raise_for_status()
            return response.text
    except Exception:
        logger.exception("FDA outbreak page fetch failed")
        return ""


def _is_active(row: dict) -> bool:
    status = (row.get("status") or "").lower()
    event = (row.get("event_status") or "").lower()
    if "closed" in status or "ended" in event:
        return False
    return "active" in status or "ongoing" in event or not status


def _parse_tables(html: str) -> list[dict]:
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.I | re.S)
    results: list[dict] = []
    for table in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.I | re.S)
        if not rows:
            continue
        header_cells = _cell_texts(rows[0])
        header_blob = " ".join(header_cells).lower()
        if "reference" not in header_blob or "pathogen" not in header_blob:
            continue
        for row_html in rows[1:]:
            cells = _cell_texts(row_html)
            hrefs = _cell_hrefs(row_html)
            if len(cells) < 6:
                continue
            item = _row_to_dict(cells, hrefs)
            if item:
                results.append(item)
    return results


def _row_to_dict(cells: list[str], hrefs: list[str]) -> dict | None:
    # Expected: Date Posted | Reference # | Pathogen | Product(s) | Case Count |
    # Investigation Status | Outbreak/Event Status | Recall | …
    date_posted = _clean(cells[0])
    ref_raw = _clean(cells[1])
    pathogen = _clean(cells[2])
    product = _clean(cells[3]) or "Not Yet Identified"
    cases = _clean(cells[4])
    status = _clean(cells[5]) if len(cells) > 5 else ""
    event_status = _clean(cells[6]) if len(cells) > 6 else ""
    recall_status = _clean(cells[7]) if len(cells) > 7 else ""

    ref_id = _extract_ref(ref_raw)
    if not ref_id or not pathogen:
        return None

    advisory = next((h for h in hrefs if h.startswith("/") or "fda.gov" in h), None)
    if advisory and advisory.startswith("/"):
        source_url = f"https://www.fda.gov{advisory}"
    elif advisory:
        source_url = advisory
    else:
        source_url = OUTBREAK_URL

    posted = _parse_date(date_posted)
    summary = (
        f"FDA foodborne outbreak investigation #{ref_id}: {pathogen}. "
        f"Linked product: {product}. Cases: {cases or 'see advisory'}. "
        f"Investigation: {status or 'Active'}."
    )

    if re.search(r"not yet identified|not identified|unidentified", product or "", re.I):
        return None
    from ..pipeline.glance_titles import glance_title, is_sensible_product

    simplified = glance_title(brand="", name=product)
    if not simplified or not is_sensible_product(simplified["brand"], simplified["name"]):
        return None
    brand = "FDA watch"
    name = simplified["name"]

    return {
        "ref_id": ref_id,
        "pathogen": pathogen,
        "status": status or "Active",
        "event_status": event_status,
        "case_count": cases,
        "product_status": product,
        "recall_status": recall_status,
        "source_url": source_url,
        "summary": summary,
        "date_posted": posted,
        "usda_ref": _extract_usda_ref(ref_raw),
        "slug": f"outbreak-{ref_id}",
        "brand": brand,
        "name": name[:180],
    }


def _extract_ref(text: str) -> str:
    m = re.search(r"\b(\d{3,5})\b", text)
    return m.group(1) if m else ""


def _extract_usda_ref(text: str) -> str | None:
    m = re.search(r"USDA\s+([\d\-]+)", text, re.I)
    return m.group(1) if m else None


def _cell_texts(row_html: str) -> list[str]:
    cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, re.I | re.S)
    return [_clean(c) for c in cells]


def _cell_hrefs(row_html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', row_html)


def _clean(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = unescape(text)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: str) -> datetime | None:
    text = _clean(value)
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
