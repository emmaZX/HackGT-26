import html
import math
import re
from datetime import datetime

from .config import get_settings

DISPLAY_NAME_RE = re.compile(r"[^a-zA-Z0-9_\- .']")
WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(value: str, max_len: int = 4000) -> str:
    cleaned = html.unescape(value or "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:max_len]


def sanitize_display_name(value: str) -> str:
    name = DISPLAY_NAME_RE.sub("", value or "").strip()
    return (name or "Neighbor")[:80]


def snap_coordinate(value: float | None) -> float | None:
    if value is None:
        return None
    decimals = get_settings().location_grid_decimals
    factor = 10**decimals
    return math.floor(value * factor + 0.5) / factor


def public_location(label: str | None, lat: float | None, lng: float | None) -> dict:
    """Never expose stored user coordinates. City label + optional city centroid only."""
    return {
        "label": label,
        "latitude": snap_coordinate(lat) if label else None,
        "longitude": snap_coordinate(lng) if label else None,
        "precision": "city" if label else "none",
    }


def iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None
