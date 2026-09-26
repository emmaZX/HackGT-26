"""
Hybrid bootstrap: CPSC catalog → fake community posts → light Brave scrape (background).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from .config import get_settings
from .data_sources.cpsc import fetch_recent_recalls
from .database import SessionLocal
from .models import Comment, DiscoveryRun, Issue, Like, Post, Product, Recall
from .seed import ISSUES, seed

logger = logging.getLogger(__name__)

HOME_SCRAPE_MARKER = "__home_scrape__"
CITIES = ["Atlanta", "Chicago", "Austin", "Boston", "Seattle", "Marietta"]


def ensure_issue_taxonomy(db: Session) -> None:
    for slug, name, description, category, icon in ISSUES:
        if db.query(Issue).filter(Issue.slug == slug).one_or_none():
            continue
        db.add(
            Issue(slug=slug, name=name, description=description, category=category, icon=icon)
        )
    db.commit()


def bootstrap_from_cpsc(db: Session) -> list[Product]:
    settings = get_settings()
    ensure_issue_taxonomy(db)

    if settings.seed_demo:
        from .seed import seed_if_empty

        seed_if_empty(db)
        return db.query(Product).all()

    existing = db.query(Product).count()
    if existing:
        from .models import Recall

        recent = (
            db.query(Recall)
            .order_by(Recall.recall_date.desc())
            .limit(settings.home_scrape_products * 3)
            .all()
        )
        products: list[Product] = []
        seen: set[int] = set()
        for recall in recent:
            if recall.product_id in seen:
                continue
            seen.add(recall.product_id)
            products.append(recall.product)
            if len(products) >= settings.home_scrape_products:
                break
        if not products:
            products = db.query(Product).limit(settings.home_scrape_products).all()
        if settings.seed_fake_posts:
            seed_fake_posts(db, products)
        return products

    logger.info("Bootstrapping products from CPSC…")
    try:
        recalls = fetch_recent_recalls(limit=settings.cpsc_recall_limit)
    except Exception:
        logger.exception("CPSC fetch failed; falling back to offline demo seed")
        seed(db)
        return db.query(Product).all()

    if not recalls:
        logger.warning("CPSC returned no recalls; falling back to offline demo seed")
        seed(db)
        return db.query(Product).all()

    products: list[Product] = []
    for item in recalls:
        product = _upsert_product_recall(db, item)
        products.append(product)
    db.commit()

    home_products = products[: settings.home_scrape_products]
    if settings.seed_fake_posts:
        seed_fake_posts(db, home_products)
    return home_products


def _upsert_product_recall(db: Session, item: dict) -> Product:
    product = db.query(Product).filter(Product.slug == item["slug"]).one_or_none()
    if not product:
        # Avoid slug collisions across similar names
        base = item["slug"]
        slug = base
        n = 2
        while db.query(Product).filter(Product.slug == slug).one_or_none():
            slug = f"{base}-{n}"[:160]
            n += 1
        product = Product(
            slug=slug,
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
    else:
        product.summary = product.summary or item.get("summary")
        product.image_url = product.image_url or item.get("image_url")

    existing_recall = (
        db.query(Recall)
        .filter(Recall.product_id == product.id, Recall.source_url == item["source_url"])
        .one_or_none()
    )
    if not existing_recall:
        db.add(
            Recall(
                product_id=product.id,
                agency=item["agency"],
                recall_date=item["recall_date"],
                reason=item["reason"],
                hazard=item["hazard"],
                source_url=item["source_url"],
                official=True,
                nationwide=item.get("nationwide", True),
            )
        )
        db.flush()
    return product


def seed_fake_posts(db: Session, products: list[Product]) -> None:
    """Neighbor-style posts for demo social proof. Not claimed as scraped evidence."""
    templates = [
        ("Saw this recall and stopped using mine.", "Same here — tossed it the same day."),
        ("Anyone else have issues before the official notice?", "Yes, mine acted weird for weeks."),
        ("Shared this with my neighbor who still has one.", "Good call — they hadn't heard."),
        ("Checking serial numbers tonight.", "Do it. Mine was in the batch."),
    ]
    for index, product in enumerate(products):
        if db.query(Post).filter(Post.product_id == product.id).count() >= 2:
            continue
        body, reply = templates[index % len(templates)]
        city = CITIES[index % len(CITIES)]
        post = Post(
            product_id=product.id,
            display_name=["Alex", "Sam", "Jordan", "Riley", "Casey"][index % 5],
            title=None,
            body=body,
            location_label=city,
            created_at=datetime.utcnow(),
        )
        db.add(post)
        db.flush()
        db.add(
            Comment(
                post_id=post.id,
                display_name=["Maya", "Chris", "Taylor"][index % 3],
                body=reply,
            )
        )
        db.add(Like(post_id=post.id, display_name="Neighbor"))
        if index % 2 == 0:
            db.add(Like(post_id=post.id, display_name="Local"))
    db.commit()


def home_scrape_already_done(db: Session) -> bool:
    return (
        db.query(DiscoveryRun)
        .filter(DiscoveryRun.query == HOME_SCRAPE_MARKER)
        .count()
        > 0
    )


def start_home_scrape_background(product_slugs: list[str]) -> None:
    settings = get_settings()
    if not settings.has_live_search() or not product_slugs:
        return

    def worker() -> None:
        from .services import run_discovery

        with SessionLocal() as db:
            if home_scrape_already_done(db):
                return
            logger.info("Starting light home scrape for %s products", len(product_slugs))
            for slug in product_slugs:
                try:
                    result = run_discovery(
                        db,
                        slug,
                        max_pages=settings.home_scrape_pages,
                        max_queries=settings.home_scrape_queries,
                        force=True,
                    )
                    logger.info(
                        "Home scrape %s: ingested=%s provider=%s",
                        slug,
                        result.get("ingested"),
                        result.get("provider"),
                    )
                except Exception:
                    logger.exception("Home scrape failed for %s", slug)
            db.add(
                DiscoveryRun(
                    product_id=None,
                    query=HOME_SCRAPE_MARKER,
                    provider="bootstrap",
                    result_count=len(product_slugs),
                    notes="light home scrape completed",
                )
            )
            db.commit()

    threading.Thread(target=worker, name="home-scrape", daemon=True).start()
