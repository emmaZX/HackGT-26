"""
Try the X search on its own:
    .venv\\Scripts\\python test_x_search.py "garden salad mix"
    .venv\\Scripts\\python test_x_search.py --debug "garden salad mix"   (shows Grok's raw answer)
    .venv\\Scripts\\python test_x_search.py --sweep illness              (find products people complain about;
                                                                  focus: illness | allergen | foreign)
Run from the backend folder. Uses XAI_API_KEY from backend/.env. Each run costs a little credit.
"""

import json
import sys
from datetime import datetime, timedelta

from app.data_sources import x_search
from app.grok import cited_urls, output_text

debug = "--debug" in sys.argv
sweep = "--sweep" in sys.argv
args = [a for a in sys.argv[1:] if a not in ("--debug", "--sweep")]
product = " ".join(args) or ("illness" if sweep else "garden salad mix")
if sweep:
    print(f"Sweeping X for recent food complaints (focus: {product}) — up to a minute or two\n")
else:
    print(f"Searching X for complaints about: {product} (this can take up to a minute or two)\n")

if debug:
    # Capture the raw response by wrapping the Grok call
    captured = {}
    original = x_search.respond

    def spy(*args, **kwargs):
        captured["response"] = original(*args, **kwargs)
        return captured["response"]

    x_search.respond = spy

if sweep:
    posts = x_search.sweep_x_food_complaints(focus=product, days=7, limit=20)
else:
    posts = x_search.search_x_complaints(product, days=30, limit=10)

if debug and "response" in captured:
    r = captured["response"]
    print("=== Grok's text answer ===")
    print(output_text(r)[:3000] or "(empty)")
    print("\n=== Source URLs the search returned ===")
    urls = sorted(cited_urls(r))
    print("\n".join(urls[:40]) if urls else "(none)")
    print("\n=== Usage (what this run was billed for) ===")
    print(json.dumps(r.get("usage"), indent=2))
    ticks = (r.get("usage") or {}).get("cost_in_usd_ticks")
    if ticks:
        print(f"≈ ${ticks / 1e10:.3f} for this run")
    print()

if not posts:
    print("No posts kept.")
for i, p in enumerate(posts, 1):
    flag = "" if p["verified_url"] else "  [URL not verified]"
    about = f"  [{p['brand'] + ' ' if p.get('brand') else ''}{p['product_name']} · {p['issue']}]" if p.get("product_name") else ""
    print(f"{i}. @{p['display_name']} · {p['created_at']} · {p['location_label'] or 'no location'}{flag}{about}")
    print(f"   {p['text'][:200]}")
    print(f"   {p['source_url']}\n")
