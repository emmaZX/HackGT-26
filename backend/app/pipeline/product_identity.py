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
    """Glanceable grocery title. Returns {brand, name}; falls back if junk."""
    from .glance_titles import glance_title

    titled = glance_title(brand=brand, name=name)
    if titled:
        return titled
    # Last resort — still keep it short; caller may reject via is_sensible_product.
    raw = (name or brand or fallback or "Food item").strip()
    raw = re.sub(r"\s+", " ", raw)[:34]
    return {"brand": (brand or "Unknown")[:28], "name": raw or fallback}


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
