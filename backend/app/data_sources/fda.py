"""
FDA food enforcement connector — openFDA food recalls (lettuce outbreaks, pathogens, etc.).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx

FDA_FOOD_ENFORCEMENT = "https://api.fda.gov/food/enforcement.json"

# Prefer outbreak / pathogen style stories for the home feed.
PRIORITY_NEEDLES = (
    "cyclospora",
    "salmonella",
    "listeria",
    "e. coli",
    "e coli",
    "escherichia",
    "hepatitis",
    "botulism",
    "norovirus",
    "contamination",
    "lettuce",
    "romaine",
    "spinach",
    "sprout",
    "cantaloupe",
    "onion",
    "cheese",
    "ice cream",
    "undeclared",
    "allergen",
)


def fetch_recent_food_recalls(limit: int = 25, days_back: int = 180) -> list[dict]:
    """Return normalized FDA food recall dicts for Product/Recall upsert."""
    start = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y%m%d")
    end = datetime.utcnow().strftime("%Y%m%d")
    pool = max(limit * 4, 40)
    queries = [
        f"report_date:[{start} TO {end}]",
        'status:"Ongoing"',
        # Bias the pool toward outbreak / produce stories for the demo.
        "(cyclospora OR salmonella OR listeria OR \"e. coli\" OR lettuce OR romaine OR spinach OR outbreak)",
        # Targeted Ongoing queries so watchlist matches aren't missed by the global limit.
        '(status:"Ongoing") AND (romaine OR lettuce OR cyclospora OR cantaloupe OR alfalfa OR sprout OR queso OR panela OR "soft cheese" OR deli OR listeria)',
    ]

    rows: list[dict] = []
    seen_ids: set[str] = set()
    with httpx.Client(timeout=40, follow_redirects=True, trust_env=False) as client:
        for search in queries:
            try:
                response = client.get(
                    FDA_FOOD_ENFORCEMENT,
                    params={
                        "search": search,
                        "sort": "report_date:desc",
                        "limit": min(pool, 100),
                    },
                )
                if response.status_code >= 400:
                    continue
                for row in response.json().get("results") or []:
                    # Only Ongoing — never attach terminated / historical notices.
                    if (row.get("status") or "").strip().lower() != "ongoing":
                        continue
                    key = str(row.get("recall_number") or row.get("event_id") or id(row))
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    rows.append(row)
            except Exception:
                continue

    normalized: list[dict] = []
    for row in rows:
        item = _normalize(row)
        if item:
            normalized.append(item)

    normalized.sort(key=lambda item: (item["_priority"], item["recall_date"]), reverse=True)

    out: list[dict] = []
    seen_slugs: set[str] = set()
    for item in normalized:
        if item["slug"] in seen_slugs:
            continue
        seen_slugs.add(item["slug"])
        item.pop("_priority", None)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _normalize(row: dict) -> dict | None:
    description = (row.get("product_description") or "").strip()
    reason = (row.get("reason_for_recall") or "").strip()
    firm = (row.get("recalling_firm") or "").strip()
    if not description or not reason:
        return None

    name = _short_product_name(description)
    brand = _short_firm(firm) or "FDA food recall"
    category = "Food"
    hazard = _hazard_label(reason, row.get("classification") or "")
    recall_date = _parse_fda_date(row.get("report_date") or row.get("recall_initiation_date"))
    if not recall_date:
        return None

    recall_number = (row.get("recall_number") or row.get("event_id") or "").strip()
    source_url = (
        f"https://www.accessdata.fda.gov/scripts/ires/index.cfm"
        f"?Event={row.get('event_id') or ''}"
        if row.get("event_id")
        else f"https://api.fda.gov/food/enforcement.json?search=recall_number:\"{recall_number}\""
    )
    if not recall_number and not row.get("event_id"):
        source_url = "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts"

    slug = _slugify(f"{brand} {name}")[:160]
    summary = f"{hazard}. {reason}"[:500]
    priority = _priority_score(description, reason, row.get("classification") or "")

    nationwide = "nationwide" in (row.get("distribution_pattern") or "").lower()
    status = (row.get("status") or "").strip() or "Unknown"

    return {
        "slug": slug,
        "brand": brand[:160],
        "name": name[:240],
        "model": None,
        "category": category,
        "manufacturer": firm[:160] if firm else None,
        "image_url": None,
        "summary": summary,
        "agency": "FDA",
        "recall_date": recall_date,
        "reason": reason[:2000],
        "hazard": hazard[:200],
        "source_url": source_url[:700],
        "recall_id": recall_number or str(row.get("event_id") or slug),
        "nationwide": nationwide,
        "status": status,
        "_priority": priority,
    }


def _short_product_name(description: str) -> str:
    # First clause before packaging noise; strip UPC/lot/net-weight into cleaner shelf names.
    from ..merge_products import clean_name

    chunk = re.split(r"[.;\n]", description, maxsplit=1)[0].strip()
    chunk = re.sub(r"\s+", " ", chunk)
    cleaned = clean_name(chunk) or chunk
    if len(cleaned) > 90:
        cleaned = cleaned[:87].rsplit(" ", 1)[0] + "…"
    return cleaned or "Food product"


def _short_firm(firm: str) -> str:
    if not firm:
        return "Unknown"
    # Drop Inc/LLC suffixes and take leading name.
    cleaned = re.split(r",\s*(?:Inc|LLC|Ltd|Co)\b", firm, flags=re.I)[0]
    cleaned = cleaned.split(" dba ")[0].split(" DBA ")[0]
    return cleaned.strip()[:80] or firm[:80]


def _hazard_label(reason: str, classification: str) -> str:
    lowered = reason.lower()
    for needle, label in (
        ("cyclospora", "Cyclospora contamination"),
        ("salmonella", "Salmonella contamination"),
        ("listeria", "Listeria contamination"),
        ("e. coli", "E. coli contamination"),
        ("escherichia", "E. coli contamination"),
        ("undeclared", "Undeclared allergen"),
        ("botulism", "Botulism risk"),
        ("hepatitis", "Hepatitis risk"),
        ("metal", "Foreign material"),
        ("plastic", "Foreign material"),
    ):
        if needle in lowered:
            return label
    if classification:
        return f"{classification} food recall"
    return "Food safety recall"


def _priority_score(description: str, reason: str, classification: str) -> int:
    text = f"{description} {reason}".lower()
    score = 0
    if classification.upper() == "CLASS I":
        score += 5
    elif classification.upper() == "CLASS II":
        score += 2
    for needle in PRIORITY_NEEDLES:
        if needle in text:
            score += 3
    return score


def _parse_fda_date(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "food-product"
