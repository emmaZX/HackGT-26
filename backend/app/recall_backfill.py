"""
Before-the-recall search: for recent official recalls, ask Grok to search X for first-person
complaints posted in the weeks BEFORE the recall date, and attach any real posts to that product.

Honesty rules:
- The post date comes from the X post ID (it encodes the exact posting time), not from Grok.
- Only posts dated before the recall are saved, each with its link.
- Nothing is invented: no posts found means nothing is saved.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from .data_sources.x_search import (
    STATUS_URL,
    _normalize,
    _parse_json_array,
    _status_id,
    status_time,
)
from .grok import cited_urls, output_text, respond
from .merge_products import clean_name, display_brand
from .models import Product, Recall, Report

logger = logging.getLogger(__name__)

PROMPT = """Search X for posts published between {start} and {end} (inclusive) where a person
describes a problem they personally had after eating this food: {product}

Only count food safety problems they or their household experienced: getting sick (vomiting,
diarrhea, food poisoning, ER or doctor visit), an allergic reaction, or finding something
dangerous in it (glass, metal, plastic, bugs, mold in a sealed package).
Skip news outlets, brand or store accounts, recall announcements, jokes, and posts about other products.

Answer with ONLY a JSON array (no prose, no code fences). At most {limit} items. Each item:
{{"url": "https://x.com/<handle>/status/<id>", "text": "the post text, verbatim",
  "author": "<handle>", "location": "city or region if stated, else null"}}
Return [] if you find none."""


def recent_active_recalls(db: Session, limit: int) -> list[tuple[Recall, Product]]:
    rows = []
    seen_products = set()
    for recall in db.query(Recall).filter(Recall.official.is_(True)).order_by(Recall.recall_date.desc()).all():
        if "[ongoing]" not in (recall.reason or "").lower()[:20] or recall.product_id in seen_products:
            continue
        product = db.get(Product, recall.product_id)
        if product:
            rows.append((recall, product))
            seen_products.add(recall.product_id)
        if len(rows) >= limit:
            break
    return rows


def search_before_recall(product: Product, recall: Recall, window_days: int = 60, limit: int = 10) -> list[dict]:
    end = recall.recall_date - timedelta(days=1)
    start = recall.recall_date - timedelta(days=window_days)
    name = clean_name(product.name, product.brand)
    brand = display_brand(product.brand)
    query = name if not brand or brand.lower() in name.lower() else f"{brand} {name}"
    response = respond(
        PROMPT.format(start=start.date(), end=end.date(), product=query, limit=limit),
        tools=[{"type": "x_search", "from_date": start.strftime("%Y-%m-%d"), "to_date": end.strftime("%Y-%m-%d")}],
    )
    cited = {i for i in (_status_id(u) for u in cited_urls(response)) if i}
    posts = []
    for item in _parse_json_array(output_text(response)):
        url = _normalize(item.get("url") or "")
        text = (item.get("text") or "").strip()
        posted = status_time(url or "")
        if not url or not text or not posted:
            continue
        if cited and _status_id(url) not in cited:
            continue  # link didn't come from the search
        if posted >= recall.recall_date:
            continue  # only posts from before the recall
        posts.append({"url": url, "text": text, "author": (item.get("author") or "").lstrip("@"),
                      "location": item.get("location") or None, "posted": posted})
    return posts


def save_before_recall(db: Session, product: Product, posts: list[dict]) -> int:
    added = 0
    for post in posts:
        m = STATUS_URL.search(post["url"])
        status_id = m.group(2) if m else post["url"]
        if db.query(Report).filter(Report.source == "x", Report.source_id == status_id).first():
            continue
        db.add(
            Report(
                product_id=product.id,
                source="x",
                source_id=status_id,
                source_url=post["url"],
                text=post["text"][:4000],
                excerpt=post["text"][:280],
                created_at=post["posted"],
                incident_date=post["posted"],
                location_label=post["location"],
                location_precision="city" if post["location"] else "none",
                location_source="post" if post["location"] else "none",
                display_name=post["author"][:80] or None,
                extra_json=json.dumps({"via": "grok_x_search_before_recall"}),
            )
        )
        added += 1
    db.commit()
    return added
