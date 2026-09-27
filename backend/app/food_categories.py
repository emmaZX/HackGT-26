"""
Fixed list of food categories, loosely following how FDA groups food recalls.
Grok must pick from these labels, so the same kind of food always lands in the same bucket
("pre-mixed salad", "garden salad kit", "bagged romaine" → Leafy greens & salad mixes).
"""

FOOD_CATEGORIES = [
    "Leafy greens & salad mixes",
    "Fresh fruits & vegetables",
    "Frozen fruits & vegetables",
    "Deli & cured meats",
    "Raw meat & poultry",
    "Seafood",
    "Eggs",
    "Milk & yogurt",
    "Cheese",
    "Infant formula & baby food",
    "Cereal, pasta & grains",
    "Bread & baked goods",
    "Chips, crackers & snacks",
    "Nuts, nut butters & seeds",
    "Candy & chocolate",
    "Juice & beverages",
    "Spices & seasonings",
    "Sauces & condiments",
    "Canned & jarred foods",
    "Frozen & prepared meals",
    "Supplements & protein powder",
    "Other food",
]

import re

_BY_LOWER = {c.lower(): c for c in FOOD_CATEGORIES}


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z]+", value.lower().replace("&", " and "))) - {"and", "the", "of"}


def normalize_category(value: str | None) -> str:
    """Map Grok's answer onto the list; anything unrecognized becomes 'Other food'."""
    if not value:
        return "Other food"
    v = value.strip().lower()
    if v in _BY_LOWER:
        return _BY_LOWER[v]
    # Tolerate wording drift ("fruits and vegetables" vs "fruits & vegetables")
    words = _words(v)
    best, score = "Other food", 0.0
    for label in FOOD_CATEGORIES:
        lw = _words(label)
        overlap = len(words & lw) / max(len(words | lw), 1)
        if overlap > score:
            best, score = label, overlap
    return best if score >= 0.5 else "Other food"


def is_food_category(value: str | None) -> bool:
    return bool(value) and value.lower() in _BY_LOWER
