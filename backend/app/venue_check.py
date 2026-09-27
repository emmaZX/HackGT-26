"""
Grok reads the title and the start of each post and answers one question: is this describing
something from a restaurant, or is it a product? Store counter food (deli, hot bar, rotisserie,
made-in-store meals) counts as restaurant. Posts labelled "restaurant" are left out of the feed.

- Posts are sent in batches, and Grok's answer is stored on the report (Report.extra_json
  "venue": "restaurant" | "product"), so each post is asked about once and the feed never
  waits on Grok.
- Posts not labelled yet still show. Nothing is hidden until Grok says "restaurant".
- Runs in the background at startup and then every VENUE_CHECK_INTERVAL minutes, but only
  calls Grok when there are unlabelled posts. Also runs after an X sweep.

Env:
  VENUE_CHECK           set to 0 to turn it off
  VENUE_CHECK_INTERVAL  minutes between background passes (default 10)

Run it right away (from the backend folder):
  .venv\\Scripts\\python run_venue_check.py          label new posts
  .venv\\Scripts\\python run_venue_check.py --redo   ask again about every post
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from .database import SessionLocal
from .grok import ai_text, grok_available
from .models import Product, Report

logger = logging.getLogger(__name__)

BATCH = 25
VENUES = {"restaurant", "product"}
_lock = threading.Lock()

PROMPT = """For each food-safety post below, read its title and the start of the post and answer:
Is this describing something from a restaurant or is it a product?

- "restaurant": food made or served to order. Restaurants, fast food, cafes, takeout, catering,
  and also store counters: deli subs and sandwiches, hot bar, salad bar, sushi counter,
  rotisserie chicken, pizza or meals made in the store.
- "product": packaged or grocery food a person buys and takes home: brand-name items, produce,
  meat, dairy, bread, snacks, frozen food, drinks, supplements.
A store name alone (Walmart, Kroger, Publix...) says nothing; judge the food itself.

Answer with ONLY a JSON array, one object per post:
[{{"id": 123, "venue": "restaurant" | "product"}}]

Posts:
{posts}"""

# iWasPoisoned page text opens with the site's report form and ends with a "Popular topics"
# tag cloud (#Taco Bell #McDonald's ...). The person's own words sit between them.
_IWP_HEADER = re.compile(r"^.*?reported by \S+[\s\W]*(?:business\s+)?", re.I | re.S)
_IWP_FOOTER = re.compile(r"\b(Popular\s+topics|Near\s+Me\s+View\s+Map|See\s+More\s+Reports)\b", re.I)


def _meta(report: Report) -> dict:
    try:
        data = json.loads(report.extra_json or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def venue_of(report: Report) -> str | None:
    return _meta(report).get("venue")


def is_restaurant_report(report: Report) -> bool:
    return venue_of(report) == "restaurant"


def _post_start(report: Report) -> str:
    body = report.text or report.excerpt or ""
    if report.source == "iwaspoisoned":
        body = _IWP_HEADER.sub("", body, count=1)
        footer = _IWP_FOOTER.search(body)
        if footer:
            body = body[: footer.start()]
    return re.sub(r"\s+", " ", body).strip()[:400]


def _post_line(report: Report, product_names: dict[int, str]) -> str:
    # iWasPoisoned post titles only name the store ("Food Safety Report: Publix, ..."), so the
    # card title the app shows for the post goes with it.
    titles = " | ".join(t for t in (product_names.get(report.product_id, ""), report.title or "") if t)
    titles = re.sub(r"\s+", " ", titles).strip()[:300]
    return f"[{report.id}] Title: {titles}\n    Post: {_post_start(report)}"


def _classify(batch: list[Report], product_names: dict[int, str]) -> dict[int, str]:
    lines = [_post_line(r, product_names) for r in batch]
    text = ai_text(PROMPT.format(posts="\n".join(lines)), timeout=90)
    match = re.search(r"\[[\s\S]*\]", text or "")
    if not match:
        return {}
    sent = {r.id for r in batch}
    out: dict[int, str] = {}
    for item in json.loads(match.group(0)):
        if not isinstance(item, dict):
            continue
        rid, venue = item.get("id"), str(item.get("venue") or "").lower()
        if isinstance(rid, int) and rid in sent and venue in VENUES:
            out[rid] = venue
    return out


def run_venue_check(limit: int | None = None, redo: bool = False) -> dict:
    """Label every post that doesn't have a venue yet (or every post, with redo)."""
    if not grok_available():
        return {"classified": 0, "restaurant": 0, "skipped": "grok not configured"}
    if not _lock.acquire(blocking=False):
        return {"classified": 0, "restaurant": 0, "skipped": "already running"}
    classified = restaurant = failed = 0
    try:
        with SessionLocal() as db:
            pending = [
                r
                for r in db.query(Report).filter(Report.is_duplicate.is_(False)).order_by(Report.id.desc()).all()
                if redo or venue_of(r) not in VENUES
            ]
            if limit is not None:
                pending = pending[:limit]
            if not pending:
                return {"classified": 0, "restaurant": 0, "pending": 0}
            ids = {r.product_id for r in pending}
            product_names = {
                p.id: f"{p.brand} {p.name}".strip()
                for p in db.query(Product).filter(Product.id.in_(list(ids))).all()
            }
            for start in range(0, len(pending), BATCH):
                batch = pending[start : start + BATCH]
                try:
                    venues = _classify(batch, product_names)
                except Exception as exc:
                    logger.warning("Venue check batch failed: %s", str(exc)[:120])
                    venues = {}
                if not venues:
                    failed += len(batch)
                    continue
                for report in batch:
                    venue = venues.get(report.id)
                    if not venue:
                        continue  # left unclassified, retried next pass
                    report.extra_json = json.dumps({**_meta(report), "venue": venue})
                    classified += 1
                    restaurant += venue == "restaurant"
                db.commit()
        if classified:
            from .feed_cache import invalidate

            invalidate()
    finally:
        _lock.release()
    result = {"classified": classified, "restaurant": restaurant, "failed": failed}
    logger.warning("Venue check done: %s", result)
    return result


def start_venue_check_background() -> None:
    if os.getenv("VENUE_CHECK", "1").strip() == "0":
        return
    interval = max(1.0, float(os.getenv("VENUE_CHECK_INTERVAL", "10") or 10)) * 60

    def worker() -> None:
        time.sleep(30)  # let startup scrapes save their reports first
        while True:
            try:
                run_venue_check()
            except Exception:
                logger.exception("Venue check pass failed")
            time.sleep(interval)

    threading.Thread(target=worker, name="venue-check", daemon=True).start()
