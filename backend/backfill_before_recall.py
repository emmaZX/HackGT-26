"""
Search X for complaints posted BEFORE recent recalls (from the backend folder):
    .venv\\Scripts\\python backfill_before_recall.py            5 most recent active recalls
    .venv\\Scripts\\python backfill_before_recall.py 10         10 recalls
Each recall is one Grok search (~10-30 cents). Then run find_lead_times.py to see results.
"""

import sys

from app.database import SessionLocal
from app.recall_backfill import recent_active_recalls, save_before_recall, search_before_recall

limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
with SessionLocal() as db:
    targets = recent_active_recalls(db, limit)
    print(f"Searching X before {len(targets)} recalls (a minute or two each)...\n")
    total = 0
    for recall, product in targets:
        try:
            posts = search_before_recall(product, recall)
        except Exception as exc:
            print(f"  {product.name[:60]}: search failed ({str(exc)[:80]})")
            continue
        added = save_before_recall(db, product, posts)
        total += added
        print(f"  {product.name[:60]} (recalled {recall.recall_date:%b %d}): {len(posts)} found, {added} new")
    print(f"\n{total} pre-recall posts saved. Run find_lead_times.py to see which pages show a lead time.")
