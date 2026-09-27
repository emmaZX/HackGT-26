"""
Category-level view: reports across every product in the same food category.

Real outbreaks often hit several brands at once (a shared supplier), which a single
product page can't show. GET /api/categories/related returns what's happening across the
product's category so the product page can surface that pattern.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func

from .database import SessionLocal
from .food_categories import is_food_category
from .models import Product, Report

router = APIRouter()
WINDOW_DAYS = 30


@router.get("/api/categories/related")
def related(category: str, exclude: str | None = None):
    if not is_food_category(category):
        return {"category": category, "window_days": WINDOW_DAYS, "total_reports": 0, "brand_count": 0, "products": []}
    since = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    with SessionLocal() as db:
        rows = (
            db.query(Product, func.count(Report.id), func.max(Report.created_at))
            .join(Report, Report.product_id == Product.id)
            .filter(Product.category == category, Report.created_at >= since, Report.is_duplicate.is_(False))
            .group_by(Product.id)
            .order_by(func.count(Report.id).desc())
            .all()
        )
    products = [
        {
            "slug": p.slug,
            "name": p.name,
            "brand": p.brand,
            "report_count": count,
            "latest": latest.isoformat() if latest else None,
            "is_current": p.slug == exclude,
        }
        for p, count, latest in rows
    ]
    brands = {p["brand"].lower() for p in products if p["brand"] and p["brand"].lower() != "unknown"}
    return {
        "category": category,
        "window_days": WINDOW_DAYS,
        "total_reports": sum(p["report_count"] for p in products),
        "brand_count": len(brands),
        "products": products,
    }
