"""
CPSC recall sync: adds recent CPSC recalls as products, with their official photo.

Kept in its own module (instead of bootstrap.py) so it doesn't collide with the
bootstrap rewrite. Runs once in the background at startup.

Env:
  CPSC_SYNC_LIMIT  how many recent recalls to pull (default 20, 0 disables)
  CPSC_SYNC_DAYS   how far back to look, in days (default 120)
"""

from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy.orm import Session

from .data_sources.cpsc import fetch_recent_recalls
from .database import SessionLocal
from .models import Product, Recall

logger = logging.getLogger(__name__)


def sync_cpsc_recalls(db: Session, limit: int = 20, days_back: int = 120) -> int:
    """Upsert recent CPSC recalls. Returns how many products were created or updated."""
    touched = 0
    for item in fetch_recent_recalls(limit=limit, days_back=days_back):
        product = db.query(Product).filter(Product.slug == item["slug"]).one_or_none()
        if product is None:
            product = Product(
                slug=item["slug"],
                brand=item["brand"],
                name=item["name"],
                model=item.get("model"),
                category=item["category"],
                manufacturer=item.get("manufacturer"),
                image_url=item.get("image_url"),
                summary=item.get("summary"),
            )
            db.add(product)
            db.flush()
            touched += 1
        elif item.get("image_url") and not product.image_url:
            product.image_url = item["image_url"]
            touched += 1

        exists = (
            db.query(Recall)
            .filter(Recall.product_id == product.id, Recall.source_url == item["source_url"])
            .one_or_none()
        )
        if not exists:
            # "[Ongoing]" prefix: purge_non_ongoing_recalls() in bootstrap.py deletes any
            # official recall without it, and signals.py only treats "[ongoing]" as active.
            db.add(
                Recall(
                    product_id=product.id,
                    agency="CPSC",
                    recall_date=item["recall_date"],
                    reason=f"[Ongoing] {item['reason']}"[:2000],
                    hazard=item["hazard"],
                    source_url=item["source_url"],
                    official=True,
                    nationwide=item.get("nationwide", True),
                )
            )
    return touched


def start_cpsc_sync_background() -> None:
    limit = int(os.getenv("CPSC_SYNC_LIMIT", "20") or 0)
    days = int(os.getenv("CPSC_SYNC_DAYS", "120") or 120)
    if limit <= 0:
        return

    def worker() -> None:
        # Let the FDA overlay thread go first; SQLite allows one writer at a time.
        time.sleep(5)
        with SessionLocal() as db:
            try:
                count = sync_cpsc_recalls(db, limit=limit, days_back=days)
                db.commit()
                logger.info("CPSC sync complete: %s products added or updated", count)
            except Exception:
                logger.exception("CPSC sync failed")
                db.rollback()

    threading.Thread(target=worker, name="cpsc-sync", daemon=True).start()
