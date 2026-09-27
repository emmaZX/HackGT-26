"""
USDA-FSIS meat/poultry recall connector.

Prefer the live FSIS JSON API. Some networks get Akamai 403; fall back to
public-domain mirrors (Recall Bench CSV, then Internet Archive calendar
snapshots) so demos stay honest without inventing recalls.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timedelta
from html import unescape

import httpx

logger = logging.getLogger(__name__)

FSIS_API = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
# Nightly public-domain mirror of the same FSIS notices (used when Akamai blocks).
RECALL_BENCH_CSV = "https://recallbench.com/data/fsis-recalls.csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/csv,text/html,*/*",
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
    with httpx.Client(timeout=45, follow_redirects=True, trust_env=False, headers=_HEADERS) as client:
        try:
            response = client.get(FSIS_API, timeout=20)
            if response.status_code < 400:
                data = response.json()
                if isinstance(data, list) and data:
                    logger.info("FSIS live API returned %s rows", len(data))
                    return data
            logger.warning("FSIS live API status=%s — trying mirrors", response.status_code)
        except Exception:
            logger.exception("FSIS live API failed — trying mirrors")

        try:
            rows = _fetch_via_recall_bench(client)
            if rows:
                return rows
        except Exception:
            logger.exception("FSIS Recall Bench fallback failed")

        try:
            rows = _fetch_via_wayback_calendar(client)
            if rows:
                return rows
        except Exception:
            logger.exception("FSIS Wayback fallback failed")

        return []


def _fetch_via_recall_bench(client: httpx.Client) -> list[dict]:
    """Public-domain CSV rebuilt nightly from FSIS notices."""
    response = client.get(RECALL_BENCH_CSV, timeout=25)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    out: list[dict] = []
    for row in reader:
        mapped = _from_recall_bench_row(row)
        if mapped:
            out.append(mapped)
    if out:
        logger.info("FSIS Recall Bench CSV returned %s rows", len(out))
    return out


def _from_recall_bench_row(row: dict) -> dict | None:
    title = (row.get("title") or "").strip()
    if not title:
        return None
    recall_type = (row.get("type") or "").strip() or "Active Recall"
    type_l = recall_type.lower()
    still_open = "active" in type_l or "alert" in type_l
    return {
        "field_title": title,
        "field_recall_number": (row.get("recall_number") or "").strip(),
        "field_recall_type": recall_type,
        "field_recall_classification": (row.get("classification") or "").strip(),
        "field_recall_reason": (row.get("reason") or title).strip(),
        "field_summary": (row.get("reason") or title).strip(),
        "field_recall_date": (row.get("recall_date") or "").strip(),
        "field_establishment": (row.get("establishment") or "").strip(),
        "field_recall_url": (row.get("url") or "").strip(),
        "field_active_notice": "True" if still_open else "False",
        "field_closed_date": "" if still_open else "closed",
        "field_archive_recall": False,
        "field_states": (row.get("states") or "").strip(),
    }


def _fetch_via_wayback_calendar(client: httpx.Client) -> list[dict]:
    """
    Skip CDX (often hangs). Probe a few calendar timestamps near now.
    """
    now = datetime.utcnow()
    stamps: list[str] = []
    for months_ago in (0, 1, 2, 4, 8):
        dt = now - timedelta(days=30 * months_ago)
        stamps.append(dt.strftime("%Y%m%d000000"))
        stamps.append(dt.strftime("%Y%m01"))
    for ts in stamps:
        url = f"https://web.archive.org/web/{ts}id_/{FSIS_API}"
        try:
            response = client.get(url, timeout=18)
        except Exception:
            logger.warning("FSIS Wayback snapshot %s timed out", ts)
            continue
        if response.status_code >= 400:
            continue
        try:
            data = response.json()
        except Exception:
            continue
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
    if closed and closed.lower() not in {"", "none", "null"}:
        # Recall Bench uses "closed" sentinel for non-active; live API uses a date.
        if "active" not in recall_type:
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
    from ..pipeline.product_identity import simplify_food_item

    polished = simplify_food_item(brand=brand, name=name, fallback="Meat / poultry")
    brand, name = polished["brand"], polished["name"]
    # Soft quality gate — keep real Active recalls even when titles are long.
    if not brand or not name or len(name) < 3:
        return None
    if re.search(r"\bexemption\s*4\b", f"{brand} {name}", re.I):
        return None

    reason_l = reason.lower()
    title_l = title.lower()
    # Skip pure import/ineligible paperwork with no shoppable product cue.
    paperwork = any(
        x in reason_l or x in title_l
        for x in (
            "import violation",
            "without the benefit of inspection",
            "without benefit of inspection",
            "without the benefit of import",
            "ineligible",
            "imported without",
        )
    )
    productish = any(
        x in name.lower() or x in title_l
        for x in (
            "beef",
            "pork",
            "chicken",
            "turkey",
            "goat",
            "lamb",
            "sausage",
            "jerky",
            "bacon",
            "ham",
            "salad",
            "soup",
            "burrito",
            "ravioli",
            "meatloaf",
            "nugget",
            "fish",
            "crackling",
        )
    )
    if paperwork and not productish:
        return None

    outbreak_related = any(
        x in reason_l for x in ("outbreak", "illness", "hospitalization", "death", "cdc", "salmonella", "listeria", "e. coli")
    )
    states = _clean_text(row.get("field_states") or "")
    nationwide = not states or "nationwide" in states.lower() or states.count(",") >= 8
    number = str(row.get("field_recall_number") or "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", f"fsis-{brand}-{name}-{number}".lower()).strip("-")[:160]

    return {
        "slug": slug or f"fsis-{number or 'notice'}"[:160],
        "brand": brand[:120],
        "name": name[:180],
        "hazard": hazard,
        "reason": reason[:500],
        "summary": f"USDA-FSIS: {hazard}"[:500],
        "recall_date": recall_date,
        "source_url": url,
        "recall_id": number or slug,
        "outbreak_related": outbreak_related,
        "agency": "USDA-FSIS",
        "status": "Ongoing",
        "nationwide": nationwide,
    }


def _brand_name(title: str, establishment: str) -> tuple[str, str]:
    text = _clean_text(title)
    # "FSIS Issues Public Health Alert for Chicken Salad Product that May Be..."
    m = re.match(
        r"^FSIS\s+(?:Issues|Retracts)\s+Public Health Alert\s+(?:for|For)\s+(.+)$",
        text,
        re.I,
    )
    if m:
        rest = m.group(1).strip()
        rest = re.sub(r"\s+due to.*$", "", rest, flags=re.I)
        rest = re.sub(r"\s+that may.*$", "", rest, flags=re.I)
        rest = re.sub(r"\s+produced without.*$", "", rest, flags=re.I)
        rest = re.sub(r"\s+imported without.*$", "", rest, flags=re.I)
        rest = re.sub(r"\s+containing\s+fda-regulated.*$", "", rest, flags=re.I)
        return "USDA-FSIS", (rest or "Meat / poultry")[:180]

    # Typical: "Ready Meats, Inc. Recalls Ready-To-Eat Beef Products..."
    m = re.match(r"^(.+?)\s+recalls?\s+(.+)$", text, re.I)
    if m:
        brand = m.group(1).strip(" ,.")
        # Collapse "Inc. and Foo, Inc." firm lists to the first firm.
        brand = re.split(r"\s+and\s+", brand, maxsplit=1)[0].strip(" ,.")
        brand = re.sub(r",?\s*(Inc\.|LLC|Corp\.|Corporation|Co\.)\s*$", "", brand, flags=re.I).strip(" ,.")
        name = m.group(2).strip()
        name = re.sub(r"\s+due to.*$", "", name, flags=re.I)
        name = re.sub(r"\s+that may.*$", "", name, flags=re.I)
        name = re.sub(r"\s+produced without.*$", "", name, flags=re.I)
        name = re.sub(r"\s+imported without.*$", "", name, flags=re.I)
        name = re.sub(r"\s+from the .*$", "", name, flags=re.I)
        return brand[:120] or "USDA-FSIS", (name or "Meat / poultry")[:180]
    est = _clean_text(establishment)
    if est:
        est = re.split(r"[;,]", est)[0].strip()
        return est[:120], text[:180]
    return "USDA-FSIS", text[:180]


def _clean_text(value) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    # Unix timestamp (live API sometimes)
    if re.fullmatch(r"\d{10,13}", text):
        try:
            ts = int(text[:10])
            return datetime.utcfromtimestamp(ts)
        except (ValueError, OSError):
            return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text[:32], fmt)
        except ValueError:
            continue
    # ISO with time
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
