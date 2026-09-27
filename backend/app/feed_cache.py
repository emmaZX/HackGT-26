"""
Short-lived in-memory homepage feed cache.

Keyed by city + a DB content revision so any new report/post/comment/like
automatically misses the cache — snapshot mode freezes crawls, not freshness.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

# Brief TTL only as a safety net; revision usually busts the cache first.
DEFAULT_TTL_SECONDS = 30.0

_lock = threading.Lock()
_store: dict[str, tuple[float, str, dict[str, Any]]] = {}


def cache_key(city: str | None) -> str:
    return (city or "").strip().lower() or "_national"


def content_revision(db: Session) -> str:
    """Fingerprint of community + evidence volume. Changes whenever the demo snapshot does."""
    from .models import Comment, Like, Post, Report

    report_n = db.query(func.count(Report.id)).scalar() or 0
    report_max = db.query(func.max(Report.id)).scalar() or 0
    post_n = db.query(func.count(Post.id)).scalar() or 0
    post_max = db.query(func.max(Post.id)).scalar() or 0
    comment_n = db.query(func.count(Comment.id)).scalar() or 0
    like_n = db.query(func.count(Like.id)).scalar() or 0
    return f"r{report_n}.{report_max}-p{post_n}.{post_max}-c{comment_n}-l{like_n}"


def get(city: str | None, revision: str) -> dict[str, Any] | None:
    key = cache_key(city)
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if not hit:
            return None
        expires, stored_rev, payload = hit
        if stored_rev != revision or now >= expires:
            _store.pop(key, None)
            return None
        return deepcopy(payload)


def set(
    city: str | None,
    payload: dict[str, Any],
    *,
    revision: str,
    ttl: float = DEFAULT_TTL_SECONDS,
) -> None:
    key = cache_key(city)
    with _lock:
        _store[key] = (time.monotonic() + max(2.0, ttl), revision, deepcopy(payload))


def invalidate() -> None:
    with _lock:
        _store.clear()
