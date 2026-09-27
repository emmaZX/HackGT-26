"""
Merge duplicate products (from the backend folder):
    .venv\\Scripts\\python merge_duplicates.py --dry-run   show what would merge, change nothing
    .venv\\Scripts\\python merge_duplicates.py             merge them
Back up data\\signal.db first if you want an undo.
"""

import sys

from app.database import SessionLocal
from app.merge_products import merge_duplicate_products

dry = "--dry-run" in sys.argv
with SessionLocal() as db:
    result = merge_duplicate_products(db, dry_run=dry)

for group in result["details"]:
    print(f"\"{group['name']}\"  ←  {len(group['merged']) + 1} products (keeping {group['kept']})")
print(f"\n{result['groups']} groups, {sum(len(g['merged']) for g in result['details'])} duplicate products "
      f"{'would be' if dry else 'were'} merged.")
if dry:
    print("Nothing changed. Run without --dry-run to merge.")
