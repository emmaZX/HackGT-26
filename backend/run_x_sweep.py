"""
Run the Grok X sweep once and save what it finds (from the backend folder):
    .venv\\Scripts\\python run_x_sweep.py           add new posts
    .venv\\Scripts\\python run_x_sweep.py --reset   delete earlier X results first, then sweep
Costs roughly 20-60 cents per run (two searches). Safe to rerun: saved posts are skipped.
"""

import sys

from app.database import SessionLocal
from app.x_sweep_job import reset_x_data, run_x_sweep

if "--reset" in sys.argv:
    with SessionLocal() as db:
        print("Reset:", reset_x_data(db))

print("Sweeping X for food complaints (last 30 days). This takes a minute or two...\n")
result = run_x_sweep()
print(f"Posts found:        {result['posts_found']}")
print(f"New reports saved:  {result['added']}")
print(f"Already saved:      {result['skipped_existing']}")
print(f"New products:       {result['new_products']}")
print("\nReload the app to see them.")
