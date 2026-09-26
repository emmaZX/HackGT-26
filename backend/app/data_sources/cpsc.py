"""
CPSC connector — pulls official recalls from the public SaferProducts API.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx

CPSC_RECALLS_API = "https://www.saferproducts.gov/RestWebServices/Recall"


def fetch_recent_recalls(limit: int = 25, days_back: int = 120) -> list[dict]:
    """Return normalized recall dicts ready for Product/Recall upsert."""
    start = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        response = client.get(
            CPSC_RECALLS_API,
            params={"format": "json", "RecallDateStart": start},
        )
        response.raise_for_status()
        rows = response.json()
    if not isinstance(rows, list):
        return []

    normalized: list[dict] = []
    for row in rows:
        item = _normalize(row)
        if item:
            normalized.append(item)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize(row: dict) -> dict | None:
    products = row.get("Products") or []
    if not products:
        return None
    primary = products[0]
    product_name = (primary.get("Name") or "").strip()
    if not product_name:
        return None

    title = (row.get("Title") or "").strip()
    brand = _brand_from_row(row, product_name, title)
    if product_name.lower().startswith(brand.lower()):
        trimmed = product_name[len(brand) :].lstrip(" -–—:")
        if len(trimmed) >= 4:
            product_name = trimmed
    model = (primary.get("Model") or "").strip() or None
    category = (primary.get("Type") or "Consumer product").strip() or "Consumer product"
    hazard = _hazard_from_row(row)
    reason = (row.get("Description") or title or hazard)[:2000]
    url = (row.get("URL") or "").strip()
    if not url.startswith("http"):
        return None

    recall_date = _parse_date(row.get("RecallDate") or row.get("LastPublishDate"))
    if not recall_date:
        return None

    manufacturers = row.get("Manufacturers") or []
    manufacturer = None
    if manufacturers:
        manufacturer = (manufacturers[0].get("Name") or "").strip() or None

    images = row.get("Images") or []
    image_url = (images[0].get("URL") or "").strip() if images else None

    recall_id = str(row.get("RecallID") or row.get("RecallNumber") or url)
    slug = _slugify(f"{brand} {product_name}")[:160]

    return {
        "slug": slug,
        "brand": brand[:160],
        "name": product_name[:240],
        "model": model[:160] if model else None,
        "category": category[:120],
        "manufacturer": manufacturer[:160] if manufacturer else None,
        "image_url": image_url[:500] if image_url else None,
        "summary": (title or reason)[:500],
        "agency": "CPSC",
        "recall_date": recall_date,
        "reason": reason,
        "hazard": hazard[:200],
        "source_url": url[:700],
        "recall_id": recall_id,
        "nationwide": True,
    }


def _brand_from_row(row: dict, product_name: str, title: str) -> str:
    manufacturers = row.get("Manufacturers") or []
    if manufacturers:
        name = (manufacturers[0].get("Name") or "").strip()
        if name and len(name) < 80:
            # Often "Foo, Inc." — take first chunk.
            return re.split(r"[,/]", name)[0].strip() or "Unknown"
    # Title pattern: "Brand Recalls Product Due to ..."
    match = re.match(r"^(.+?)\s+Recalls\s+", title, re.I)
    if match:
        return match.group(1).strip()[:160]
    first = product_name.split()[0]
    return first[:160] if first else "Unknown"


def _hazard_from_row(row: dict) -> str:
    hazards = row.get("Hazards") or []
    if hazards:
        name = (hazards[0].get("Name") or "").strip()
        if name:
            return name
    title = row.get("Title") or ""
    match = re.search(r"Due to (.+)$", title, re.I)
    if match:
        return match.group(1).strip()
    return "Safety hazard"


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if "T" in text else text[:10], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "product"
