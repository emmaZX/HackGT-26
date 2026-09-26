"""Agent 5 — Extract coarse geography clues from complaint text."""

from __future__ import annotations

import re

# Common US city clues that show up in Reddit / reviews.
CITY_HINTS = [
    "Atlanta", "Austin", "Boston", "Chicago", "Dallas", "Denver", "Detroit",
    "Houston", "Los Angeles", "Miami", "Minneapolis", "Nashville", "New York",
    "Philadelphia", "Phoenix", "Portland", "San Diego", "San Francisco",
    "Seattle", "Washington", "Marietta", "Decatur", "Brooklyn", "Queens",
]

STATE_HINTS = {
    "GA": "Georgia",
    "TX": "Texas",
    "CA": "California",
    "NY": "New York",
    "FL": "Florida",
    "IL": "Illinois",
    "WA": "Washington",
    "OH": "Ohio",
    "PA": "Pennsylvania",
}


def correlate_location(text: str, title: str | None = None) -> dict:
    """
    Return coarse location hints from free text.
    Never claims precision better than city/state.
    """
    blob = f"{title or ''}\n{text}"
    for city in CITY_HINTS:
        if re.search(rf"\b{re.escape(city)}\b", blob, re.I):
            return {
                "location_label": city,
                "location_precision": "city",
                "location_source": "inferred",
            }
    for abbr, name in STATE_HINTS.items():
        if re.search(rf"\b{abbr}\b", blob) or re.search(rf"\b{name}\b", blob, re.I):
            return {
                "location_label": name,
                "location_precision": "region",
                "location_source": "inferred",
            }
    # Phrases like "here in Ohio" / "in Ohio"
    match = re.search(r"\b(?:here in|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", blob)
    if match:
        place = match.group(1)
        if place.lower() not in {"the", "this", "our", "my", "a"}:
            return {
                "location_label": place[:80],
                "location_precision": "region",
                "location_source": "inferred",
            }
    return {
        "location_label": None,
        "location_precision": "none",
        "location_source": "none",
    }
