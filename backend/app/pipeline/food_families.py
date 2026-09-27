"""
Food-family expansion for search.

Maps brand / product needles → related catalog keywords so a miss like
"haagen dazs" still surfaces ice cream, dairy, frozen dessert, etc.
"""

from __future__ import annotations

import re

# Each family: trigger needles (in the query) → expansion keywords to OR-match
# against product name/brand/summary/slug.
FOOD_FAMILIES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (
        (
            "haagen",
            "häagen",
            "dazs",
            "ben jerry",
            "ben & jerry",
            "breyers",
            "blue bell",
            "talenti",
            "magnum",
            "ice cream",
            "gelato",
            "sorbet",
            "frozen yogurt",
            "froyo",
        ),
        (
            "ice cream",
            "gelato",
            "sorbet",
            "frozen yogurt",
            "dairy",
            "milk",
            "cream",
            "pint",
            "dessert",
        ),
    ),
    (
        ("yogurt", "yoghurt", "chobani", "fage", "siggi", "actinia"),
        ("yogurt", "yoghurt", "dairy", "milk", "greek yogurt"),
    ),
    (
        ("milk", "oatly", "fairlife", "horizon", "lactaid", "dairy"),
        ("milk", "dairy", "cream", "half and half", "yogurt", "cheese"),
    ),
    (
        ("cheese", "kraft", "velveeta", "sargento", "tillamook", "queso", "panela"),
        ("cheese", "dairy", "queso", "cheddar", "mozarella", "ricotta"),
    ),
    (
        ("butter", "margarine", "country crock", "land o lakes"),
        ("butter", "margarine", "dairy", "spread"),
    ),
    (
        (
            "chicken",
            "turkey",
            "beef",
            "pork",
            "goat",
            "meat",
            "sausage",
            "deli",
            "ground",
            "tyson",
            "perdue",
            "butterball",
        ),
        (
            "chicken",
            "turkey",
            "beef",
            "pork",
            "goat",
            "meat",
            "sausage",
            "deli",
            "poultry",
            "ground",
        ),
    ),
    (
        ("lettuce", "romaine", "spinach", "salad", "greens", "leafy"),
        ("lettuce", "romaine", "spinach", "salad", "greens", "leafy", "produce"),
    ),
    (
        ("cantaloupe", "melon", "honeydew", "watermelon"),
        ("cantaloupe", "melon", "honeydew", "watermelon", "produce", "fruit"),
    ),
    (
        ("sprout", "alfalfa", "clover sprouts"),
        ("sprout", "alfalfa", "produce"),
    ),
    (
        ("protein", "premier protein", "shake", "ensure", "boost"),
        ("protein", "shake", "rtd", "meal replacement", "nutritional"),
    ),
    (
        ("gushers", "fruit snack", "betty crocker", "candy", "gummy"),
        ("gushers", "fruit snack", "candy", "gummy", "snack"),
    ),
    (
        ("hellofresh", "meal kit", "blue apron", "factor meals"),
        ("meal kit", "hellofresh", "prepared", "chicken", "beef"),
    ),
    (
        ("salmon", "tuna", "shrimp", "seafood", "fish", "oyster", "crab"),
        ("salmon", "tuna", "shrimp", "seafood", "fish", "oyster", "crab"),
    ),
]


def related_food_keywords(query: str) -> list[str]:
    """Return related catalog keywords for a query (deduped, lowercased)."""
    text = re.sub(r"\s+", " ", (query or "").lower()).strip()
    if not text:
        return []
    # Normalize common misspellings / punctuation for brand matches.
    compact = text.replace("'", "").replace("-", " ").replace("&", " and ")
    compact = re.sub(r"[^a-z0-9\s]", "", compact)
    out: list[str] = []
    seen: set[str] = set()
    for needles, keywords in FOOD_FAMILIES:
        if any(n in compact or n in text for n in needles):
            for kw in keywords:
                key = kw.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(kw)
    return out
