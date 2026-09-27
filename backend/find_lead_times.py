"""
List products where a dated, linked public report came before the official recall
(from the backend folder):  .venv\Scripts\python find_lead_times.py
These are the product pages that will show "Spotted N days before the recall".
"""

from app.database import SessionLocal
from app.models import Product, Recall, Report

PUBLIC = {"web", "reddit", "news", "x", "iwaspoisoned"}

with SessionLocal() as db:
    rows = []
    for recall in db.query(Recall).filter(Recall.official.is_(True)).all():
        if "[ongoing]" not in (recall.reason or "").lower()[:20]:
            continue
        reports = (
            db.query(Report)
            .filter(
                Report.product_id == recall.product_id,
                Report.source.in_(PUBLIC),
                Report.source_url.isnot(None),
                Report.incident_date.isnot(None),
                Report.incident_date < recall.recall_date,
                Report.is_duplicate.is_(False),
            )
            .order_by(Report.incident_date)
            .all()
        )
        if reports:
            days = (recall.recall_date - reports[0].incident_date).days
            if days >= 1:
                product = db.get(Product, recall.product_id)
                rows.append((days, len(reports), product.slug, product.brand, product.name))
    for days, n, slug, brand, name in sorted(rows, reverse=True):
        print(f"{days:>4} days early · {n} reports · {brand} | {name}\n       /product/{slug}")
    if not rows:
        print("No product has a dated public report before its recall yet.")
