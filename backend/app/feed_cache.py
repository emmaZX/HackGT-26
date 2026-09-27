"""
Short-lived in-memory homepage feed cache.

News sites do not recompute the front page on every hit — they serve a
recent snapshot and refresh it in the background. Same idea here.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any

# Homepage can lag a bit; 45s keeps demos snappy without feeling stale.
DEFAULT_TTL_SECONDS = 45.0

_lock = threading.Lock()
_store: dict[str, tuple[float, dict[str, Any]]] = {}


def cache_key(city: str | None) -> str:
    return (city or "").strip().lower() or "_national"


def get(city: str | None) -> dict[str, Any] | None:
    key = cache_key(city)
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if not hit:
            return None
        expires, payload = hit
        if now >= expires:
            _store.pop(key, None)
            return None
        return deepcopy(payload)


def set(city: str | None, payload: dict[str, Any], *, ttl: float = DEFAULT_TTL_SECONDS) -> None:
    key = cache_key(city)
    with _lock:
        _store[key] = (time.monotonic() + max(5.0, ttl), deepcopy(payload))


def invalidate() -> None:
    with _lock:
        _store.clear()
