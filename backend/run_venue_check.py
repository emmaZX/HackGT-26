"""
Have Grok label posts as restaurant / product from their title and opening (from the backend folder):
    .venv\\Scripts\\python run_venue_check.py          only posts not labeled yet
    .venv\\Scripts\\python run_venue_check.py --redo   ask again about every post
"""

import sys

from app.venue_check import run_venue_check

redo = "--redo" in sys.argv
print("Asking Grok whether each post is a restaurant or a product...\n")
result = run_venue_check(redo=redo)
for key, value in result.items():
    print(f"{key:12} {value}")
print("\nReload the app to see the updated feed.")
