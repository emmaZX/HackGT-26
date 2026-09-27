"""Normalize messy user product names into brand + Title Case catalog identity."""

from __future__ import annotations

import json
import re

from ..config import get_settings
from ..security import sanitize_text

# Lightweight brand hints when Gemini is unavailable.
KNOWN_HINTS: list[tuple[str, str, str, str]] = [
    # needle → brand, notable product title (shown first), category
    ("gushers", "Betty Crocker", "Gushers", "Food"),
    ("fruit gushers", "Betty Crocker", "Gushers", "Food"),
    ("hellofresh", "HelloFresh", "Meal kit", "Food"),
    ("hello fresh", "HelloFresh", "Meal kit", "Food"),
    ("premier protein", "Premier Protein", "Protein shake", "Food"),
    ("protein powder", "Unknown", "Protein powder", "Food"),
    ("haagen dazs", "Häagen-Dazs", "Ice cream", "Food"),
    ("häagen-dazs", "Häagen-Dazs", "Ice cream", "Food"),
    ("haagen-dazs", "Häagen-Dazs", "Ice cream", "Food"),
    ("ben jerry", "Ben & Jerry's", "Ice cream", "Food"),
    ("ben & jerry", "Ben & Jerry's", "Ice cream", "Food"),
]


def normalize_product_identity(
    raw_name: str,
    *,
    brand: str | None = None,
    context: str | None = None,
) -> dict:
    """
    Return {brand, name, category, aliases, method} for catalog create/match.
    Never invents a recall — only cleans naming.
    """
    name = sanitize_text(raw_name, 200)
    brand_in = sanitize_text(brand or "", 120)
    if not name:
        return {
            "brand": brand_in or "Unknown",
            "name": "Unknown product",
            "category": "Uncategorized",
            "aliases": [],
            "method": "empty",
        }

    # Prefer deterministic brand hints before calling Gemini.
    hinted = _hint_normalize(name, brand_in)
    if hinted:
        return hinted

    settings = get_settings()
    if settings.gemini_api_key:
        try:
            return _gemini_normalize(name, brand_in, context or "", settings)
        except Exception:
            pass
    return _heuristic_normalize(name, brand_in)


def _hint_normalize(name: str, brand: str) -> dict | None:
    lowered = f"{brand} {name}".lower().strip()
    for needle, known_brand, known_name, category in KNOWN_HINTS:
        if needle in lowered:
            return {
                "brand": known_brand,
                "name": known_name,
                "category": category,
                "aliases": _uniq([name, known_name, needle]),
                "method": "heuristic-hint",
            }
    return None


def _heuristic_normalize(name: str, brand: str) -> dict:
    titled = _title_case_product(name)
    brand_out = _title_case_product(brand) if brand else "Unknown"
    lowered = f"{brand} {name}".lower().strip()
    return {
        "brand": brand_out,
        "name": titled,
        "category": "Food" if _looks_food(lowered) else "Uncategorized",
        "aliases": _uniq([name, titled, name.lower()]),
        "method": "heuristic",
    }


def _gemini_normalize(name: str, brand: str, context: str, settings) -> dict:
    import httpx

    prompt = (
        "You normalize consumer product names for a food/product safety catalog.\n"
        "Given a messy user-typed product label (and optional report text), return JSON ONLY:\n"
        '{"brand":"...","name":"...","category":"Food|Beverage|Supplement|Personal Care|Other",'
        '"aliases":["optional other spellings"]}\n'
        "Rules:\n"
        "- \"name\" is the notable consumer title people recognize first "
        "(e.g. Gushers, not Betty Crocker Fruit Gushers).\n"
        "- \"brand\" is the company/maker when known (e.g. Betty Crocker); otherwise \"Unknown\".\n"
        "- Use proper Title Case. Keep name short and searchable.\n"
        "- Do not invent lot numbers, recalls, or hazards.\n"
        f"User product: {name}\n"
        f"User brand: {brand or '(none)'}\n"
        f"Report context (may be empty): {context[:500]}\n"
    )
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=25,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"gemini {response.status_code}")
    text = ""
    for candidate in response.json().get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text") or ""
    match = re.search(r"\{[\s\S]*\}", text)
    data = json.loads(match.group(0) if match else text)
    brand_out = sanitize_text(str(data.get("brand") or "Unknown"), 120) or "Unknown"
    name_out = sanitize_text(str(data.get("name") or name), 200) or _title_case_product(name)
    category = sanitize_text(str(data.get("category") or "Food"), 80) or "Food"
    aliases = data.get("aliases") if isinstance(data.get("aliases"), list) else []
    alias_list = [sanitize_text(str(a), 120) for a in aliases if sanitize_text(str(a), 120)]
    alias_list.extend([name, name_out, name.lower()])
    return {
        "brand": brand_out,
        "name": name_out,
        "category": category,
        "aliases": _uniq(alias_list),
        "method": "gemini",
    }


def simplify_food_item(*, brand: str | None, name: str | None, fallback: str = "Food item") -> dict:
    """
    Turn regulator notice titles into short grocery-style item names.
    Returns {brand, name} — name is the consumer-facing item.
    """
    brand_raw = _clean_listish(brand)
    name_raw = _clean_listish(name) or brand_raw or fallback
    blob = name_raw

    # Strip common FSIS / FDA notice wrappers.
    patterns = [
        r"^FSIS\s+Issues\s+Public\s+Health\s+Alert\s+for\s+",
        r"^FSIS\s+Issues\s+Public\s+Health\s+Alert\s+",
        r"^USDA[- ]?FSIS\s+",
        r"^FDA\s+Outbreak\s+Watch\s*[—\-:]?\s*",
        r"^Public\s+Health\s+Alert\s+for\s+",
    ]
    for pat in patterns:
        blob = re.sub(pat, "", blob, flags=re.I).strip()

    # "Company Recalls PRODUCT Due to …"
    m = re.match(r"^(.*?)\s+Recalls?\s+(.*?)\s+Due\s+to\b(.*)$", blob, re.I)
    if m:
        company = m.group(1).strip()
        product = m.group(2).strip()
        return {
            "brand": _short_brand(brand_raw or company),
            "name": _short_item(product),
        }

    # "… for PRODUCT due to HAZARD"
    m = re.match(r"^(.*?)\s+due\s+to\b.*$", blob, re.I)
    if m and len(m.group(1).strip()) >= 4:
        blob = m.group(1).strip()

    # "PRODUCT linked to / associated with …"
    blob = re.sub(
        r"\s+(linked|associated)\s+to\b.*$",
        "",
        blob,
        flags=re.I,
    ).strip()

    # Leftover "Company Recalls PRODUCT" without Due to
    m = re.match(r"^(.*?)\s+Recalls?\s+(.*)$", blob, re.I)
    if m and len(m.group(2).strip()) >= 3:
        company = m.group(1).strip()
        product = m.group(2).strip()
        return {
            "brand": _short_brand(brand_raw or company),
            "name": _short_item(product),
        }

    # Pathogen — Product → keep product as name
    if "—" in blob or " - " in blob:
        parts = re.split(r"\s*[—\-]\s*", blob, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            left, right = parts[0].strip(), parts[1].strip()
            # Prefer the food product side as the title.
            if _looks_food(right.lower()) or re.search(
                r"not yet identified|not identified|unidentified", right, re.I
            ):
                item = right
                brand_out = brand_raw if brand_raw and "outbreak" not in brand_raw.lower() else ""
                if re.search(r"not yet identified|not identified", item, re.I):
                    item = "Unidentified food"
                return {"brand": _short_brand(brand_out) or "FDA watch", "name": _short_item(item)}
            blob = right

    # HelloFresh meal-kit phrasing → short item
    if re.search(r"hello\s*fresh", blob, re.I):
        if re.search(r"ground\s+beef", blob, re.I):
            return {"brand": "HelloFresh", "name": "Ground beef"}
        return {"brand": "HelloFresh", "name": "Meal kit"}

    item = _short_item(blob)
    brand_out = _short_brand(brand_raw)
    if brand_out and brand_out.lower() == item.lower():
        brand_out = ""
    # If brand still looks like a full alert sentence, drop it.
    if brand_out and (
        "public health alert" in brand_out.lower()
        or "issues public" in brand_out.lower()
        or len(brand_out) > 48
    ):
        brand_out = ""
    if not item or item.lower() in {"fsis", "fda", "usda", "alert"}:
        item = fallback
    return {"brand": brand_out or "Unknown", "name": item}


def _clean_listish(value: str | None) -> str:
    text = sanitize_text(str(value or ""), 240)
    if text.startswith("[") and text.endswith("]"):
        inner = text.strip("[]")
        parts = [p.strip(" '\"") for p in re.split(r",", inner) if p.strip(" '\"")]
        text = parts[0] if parts else text
    text = re.sub(r"^\[\s*'|^\[\s*\"|'\]\s*$|\"\]\s*$", "", text).strip(" '\"")
    return re.sub(r"\s+", " ", text).strip()


def _short_brand(value: str) -> str:
    text = _clean_listish(value)
    if not text:
        return ""
    if text.lower() in {"fda watch", "fda outbreak watch"}:
        return "FDA watch"
    # Drop LLC / Inc suffixes for card brevity.
    text = re.sub(
        r",?\s*\b(LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.|Ltd\.?)\b\.?\s*$",
        "",
        text,
        flags=re.I,
    ).strip()
    return _title_case_product(text)[:48]


def _short_item(value: str) -> str:
    text = _clean_listish(value)
    text = re.sub(r"\bproducts?\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    # Keep multi-protein FSIS titles intact (pork, beef, and goat).
    if re.search(r"\b(pork|beef|goat|chicken|turkey).*\b(and|,)\b", text, re.I):
        return _title_case_product(text)[:90] or "Food item"
    # Prefer first clause if it's a laundry list.
    if len(text) > 56 and "," in text:
        text = text.split(",")[0].strip()
    return _title_case_product(text)[:72] or "Food item"


def _title_case_product(value: str) -> str:
    small = {"of", "and", "the", "a", "an", "or", "for", "with"}
    words = re.split(r"(\s+|-)", value.strip())
    out: list[str] = []
    for i, word in enumerate(words):
        if not word or word.isspace() or word == "-":
            out.append(word)
            continue
        lower = word.lower()
        if i > 0 and lower in small:
            out.append(lower)
        else:
            out.append(lower[:1].upper() + lower[1:] if lower else word)
    return "".join(out) or value


def _looks_food(text: str) -> bool:
    needles = (
        "food",
        "snack",
        "candy",
        "gummy",
        "chip",
        "cereal",
        "drink",
        "juice",
        "milk",
        "cheese",
        "meat",
        "chicken",
        "protein",
        "shake",
        "yogurt",
        "soup",
        "sauce",
        "gushers",
    )
    return any(n in text for n in needles)


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out
