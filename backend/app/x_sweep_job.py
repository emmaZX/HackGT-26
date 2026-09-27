"""
Turn Grok X-sweep results into products + reports. Runs only when triggered:
  - command line:  .venv\\Scripts\\python run_x_sweep.py
  - HTTP (demo):   POST /api/admin/x-sweep  with header  X-Admin-Token: <ADMIN_TOKEN from .env>

Each post becomes a Report with source="x" and its link, attached to an existing product
(matched by brand + name) or to a new Food product. Posts already saved are skipped, so
running it twice never double-counts.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy.orm import Session

from .data_sources.x_search import STATUS_URL, sweep_x_food_complaints
from .food_categories import is_food_category
from .database import SessionLocal
from .models import Issue, Product, Report, ReportIssue

logger = logging.getLogger(__name__)

# The two sweeps that returned real, product-named posts in testing
DEFAULT_FOCUSES = [
    "foreign",
    "complaining to a food brand's X account that the product made them sick, or that they found something in it",
]

ISSUES = {
    "foreign_object": ("foreign-object", "Foreign object", "Something that shouldn't be there: glass, metal, plastic, bugs, mold."),
    "allergen": ("undeclared-allergen", "Allergic reaction", "Allergic reaction, often to an allergen missing from the label."),
    "illness": ("illness-after-eating", "Illness after eating", "Vomiting, diarrhea, or other illness after eating the product."),
}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:160] or "product"


def _issue(db: Session, key: str) -> Issue:
    slug, name, description = ISSUES.get(key, ISSUES["illness"])
    issue = db.query(Issue).filter(Issue.slug == slug).one_or_none()
    if issue is None:
        issue = Issue(slug=slug, name=name, description=description, category="food", icon="•")
        db.add(issue)
        db.flush()
    return issue


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower())) - {"the", "a", "of", "and", "bag", "box", "pack"}


def _similar(a: str, b: str) -> bool:
    """Loose name match: one contains the other, or at least half the words overlap."""
    a, b = a.lower().strip(), b.lower().strip()
    if a in b or b in a:
        return True
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def _product(db: Session, name: str, brand: str | None, category: str) -> tuple[Product, bool]:
    """
    Branded post  → one product per brand per category (reused on later posts).
    Unbranded post → the category's shared bucket ("Leafy greens & salad mixes", brand Unknown),
    so unbranded reports about the same kind of food pile up in one place instead of
    creating a vague new product each time.
    """
    brand = (brand or "").strip()
    if brand.lower() in {"", "unknown", "none", "null", "generic", "store brand"}:
        brand = ""
    name = name.strip()

    if not brand:
        slug = _slugify(f"category {category}")
        bucket = db.query(Product).filter(Product.slug == slug).one_or_none()
        if bucket:
            return bucket, False
        bucket = Product(
            slug=slug,
            brand="Unknown",
            name=category,
            category=category,
            summary=f"Unbranded complaints about {category.lower()} found on X.",
        )
        db.add(bucket)
        db.flush()
        return bucket, True

    name = re.sub(r"^(?:an?\s+|the\s+)?(?:bag|box|pack|package|can|jar|bottle|carton|container)s?\s+of\s+", "", name, flags=re.I)
    if name.lower().startswith(brand.lower()):
        rest = re.sub(r"^(?:'s|’s)?\s*(?:brand\s+)?", "", name[len(brand):].strip(" -–:"), flags=re.I)
        name = rest or name

    same_brand = db.query(Product).filter(Product.brand.ilike(brand)).all()
    # Same brand + same category = same product line ("frozen veggies" and "frozen vegetable
    # blend" from Green Giant end up together). Posts rarely name the exact SKU anyway.
    for existing in same_brand:
        if existing.category == category:
            return existing, False
    # Older products (from other sources) that predate the category list: match by name
    for existing in same_brand:
        if not is_food_category(existing.category) and _similar(existing.name, name):
            existing.category = category  # adopt the shared category list
            return existing, False

    product = Product(
        slug=_slugify(f"{brand} {name}"),
        brand=brand,
        name=name[:240],
        category=category,
        summary="Found from public complaints on X.",
    )
    if db.query(Product).filter(Product.slug == product.slug).first():
        product.slug = _slugify(f"{brand} {name} {category}")
    db.add(product)
    db.flush()
    return product, True


def _date(value: str | None) -> datetime:
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d")
    except ValueError:
        return datetime.utcnow()


def save_posts(db: Session, posts: list[dict]) -> dict:
    added = skipped = new_products = 0
    for post in posts:
        m = STATUS_URL.search(post["source_url"])
        status_id = m.group(2) if m else post["source_url"]
        if db.query(Report).filter(Report.source == "x", Report.source_id == status_id).first():
            skipped += 1
            continue
        product, created = _product(db, post["product_name"], post.get("brand"), post.get("category") or "Other food")
        new_products += int(created)
        text = post["text"]
        report = Report(
            product_id=product.id,
            source="x",
            source_id=status_id,
            source_url=post["source_url"],
            text=text,
            excerpt=text[:280],
            created_at=_date(post.get("created_at")),
            location_label=post.get("location_label"),
            location_precision="city" if post.get("location_label") else "none",
            location_source="post" if post.get("location_label") else "none",
            is_user_generated=False,
            display_name=post.get("display_name"),
            extra_json=json.dumps({"via": "grok_x_search", "issue": post.get("issue")}),
        )
        db.add(report)
        db.flush()
        db.add(ReportIssue(report_id=report.id, issue_id=_issue(db, post.get("issue") or "illness").id, confidence=0.8))
        try:
            from .pipeline.cluster import attach_and_dedupe

            attach_and_dedupe(db, report)  # embeddings + repost detection, same as other sources
        except Exception:
            logger.exception("Clustering failed for X report %s; saved without it", status_id)
        added += 1
    db.commit()
    return {"added": added, "skipped_existing": skipped, "new_products": new_products}


def reset_x_data(db: Session) -> dict:
    """Delete everything the X sweep saved (reports with source="x" and products only it created)."""
    from .models import Embedding

    reports = db.query(Report).filter(Report.source == "x").all()
    product_ids = {r.product_id for r in reports}
    ids = [r.id for r in reports]
    if ids:
        db.query(Embedding).filter(Embedding.report_id.in_(ids)).delete(synchronize_session=False)
        db.query(Report).filter(Report.duplicate_of_id.in_(ids)).update(
            {Report.duplicate_of_id: None, Report.is_duplicate: False}, synchronize_session=False
        )
    for r in reports:
        db.delete(r)
    db.flush()
    removed_products = 0
    for pid in product_ids:
        p = db.get(Product, pid)
        if p is None:
            continue
        summary = p.summary or ""
        made_by_sweep = summary == "Found from public complaints on X." or summary.endswith("found on X.")
        if made_by_sweep and not db.query(Report).filter(Report.product_id == pid).first() and not p.recalls and not p.posts:
            db.delete(p)
            removed_products += 1
    db.commit()
    return {"reports_removed": len(reports), "products_removed": removed_products}


def run_x_sweep(focuses: list[str] | None = None, days: int = 30, limit: int = 20) -> dict:
    posts: list[dict] = []
    for focus in focuses or DEFAULT_FOCUSES:
        posts.extend(sweep_x_food_complaints(focus=focus, days=days, limit=limit))
    with SessionLocal() as db:
        result = save_posts(db, posts)
    result["posts_found"] = len(posts)
    return result


router = APIRouter()


@router.post("/api/admin/x-sweep")
def trigger_x_sweep(x_admin_token: str | None = Header(default=None)):
    """Demo trigger. Blocks for a minute or two while Grok searches X."""
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    if not expected or x_admin_token != expected:
        raise HTTPException(403, "Set ADMIN_TOKEN in backend/.env and send it as X-Admin-Token.")
    return run_x_sweep()
