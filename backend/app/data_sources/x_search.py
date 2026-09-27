"""
Find first-person food safety complaints about a food product on X, using Grok's server-side x_search tool.

Returns report-shaped dicts (source="x") that the discovery pipeline can ingest like any
other source. Posts are only kept if their URL is one the search actually returned, so a
link the model made up never becomes evidence.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from ..food_categories import FOOD_CATEGORIES, normalize_category
from ..grok import GrokError, cited_urls, output_text, respond

logger = logging.getLogger(__name__)

STATUS_URL = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")

PROMPT = """Search X for posts from the last {days} days where a person describes a problem they
personally had after eating or drinking this food product: {product}

Only count FOOD SAFETY problems they (or their household) experienced: getting sick (vomiting,
diarrhea, stomach cramps, fever, food poisoning, ER or doctor visit), an allergic reaction
(including undeclared allergens), or finding something dangerous in it (glass, metal, plastic,
bugs, mold in a sealed package).
Skip: food that just tasted bad, was stale, or was overpriced; recipes and reviews; news
outlets, brand or store accounts, recall announcements; jokes; questions with no experience
described; and posts about a different product.

Answer with ONLY a JSON array (no prose, no code fences). At most {limit} items. Each item:
{{"url": "https://x.com/<handle>/status/<id>",
  "text": "the post text, verbatim",
  "author": "<handle>",
  "posted_at": "YYYY-MM-DD",
  "location": "city or region if the post states one, else null"}}
Return [] if you find none."""


def _normalize(url: str) -> str | None:
    m = STATUS_URL.search(url or "")
    return f"https://x.com/{m.group(1)}/status/{m.group(2)}" if m else None


def _status_id(url: str) -> str | None:
    # Search citations use x.com/i/status/<id> (no handle), so verify by post ID
    m = STATUS_URL.search(url or "")
    return m.group(2) if m else None


def _parse_json_array(text: str) -> list[dict]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


def search_x_complaints(product: str, days: int = 30, limit: int = 10) -> list[dict]:
    """First-person complaint posts about `product` from X. Empty list if none or on error."""
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        response = respond(
            PROMPT.format(product=product, days=days, limit=limit),
            tools=[{"type": "x_search", "from_date": from_date}],
        )
    except (GrokError, Exception) as exc:  # network errors included
        logger.warning("X search failed for %r: %s", product, exc)
        return []

    cited = {i for i in (_status_id(u) for u in cited_urls(response)) if i}
    posts: list[dict] = []
    seen: set[str] = set()
    for item in _parse_json_array(output_text(response)):
        url = _normalize(item.get("url") or "")
        text = (item.get("text") or "").strip()
        if not url or not text or url in seen:
            continue
        verified = _status_id(url) in cited
        if cited and not verified:
            continue  # the search never returned this link: don't trust it
        seen.add(url)
        posts.append(
            {
                "source": "x",
                "source_url": url,
                "text": text[:4000],
                "title": None,
                "display_name": (item.get("author") or url.split("/")[3]).lstrip("@")[:80],
                "created_at": item.get("posted_at"),
                "location_label": item.get("location") or None,
                "verified_url": verified,
            }
        )
    if not cited and posts:
        logger.warning("X search returned no citation list; %s posts are unverified", len(posts))
    return posts[:limit]


# ---------------------------------------------------------------------------
# Broad sweep: find the products people are complaining about, instead of
# searching product by product (which only finds problems we already suspect).
# ---------------------------------------------------------------------------

SWEEP_FOCUS = {
    "illness": "getting sick (vomiting, diarrhea, food poisoning, ER or doctor visit)",
    "allergen": "an allergic reaction, especially to an allergen not listed on the label",
    "foreign": "finding something dangerous in it (glass, metal, plastic, bugs, mold in a sealed package)",
}

SWEEP_PROMPT = """Search X for posts from the last {days} days where a person says they (or their household)
had this problem after eating or drinking a specific packaged or grocery food product:
{focus}

The post must name, or clearly identify, the product or brand. Skip restaurants and fast food,
news outlets, brand or store accounts, recall announcements, jokes, and posts with no personal
experience.

Answer with ONLY a JSON array (no prose, no code fences). At most {limit} items. Each item:
{{"url": "https://x.com/<handle>/status/<id>",
  "text": "the post text, verbatim",
  "author": "<handle>",
  "posted_at": "YYYY-MM-DD",
  "location": "city or region if the post states one, else null",
  "product": "the product as named in the post, e.g. 'garden salad mix'",
  "brand": "the brand if named, else null",
  "category": "exactly one of: {categories}",
  "issue": "illness | allergen | foreign_object"}}
Return [] if you find none."""


def sweep_x_food_complaints(focus: str = "illness", days: int = 7, limit: int = 20) -> list[dict]:
    """Recent first-person food safety complaints on X, each tagged with the product it names."""
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        response = respond(
            SWEEP_PROMPT.format(
                focus=SWEEP_FOCUS.get(focus, focus),
                days=days,
                limit=limit,
                categories=" | ".join(FOOD_CATEGORIES),
            ),
            tools=[{"type": "x_search", "from_date": from_date}],
        )
    except Exception as exc:
        logger.warning("X sweep failed (%s): %s", focus, exc)
        return []

    cited = {i for i in (_status_id(u) for u in cited_urls(response)) if i}
    posts: list[dict] = []
    seen: set[str] = set()
    for item in _parse_json_array(output_text(response)):
        url = _normalize(item.get("url") or "")
        text = (item.get("text") or "").strip()
        product = (item.get("product") or "").strip()
        if not url or not text or not product or url in seen:
            continue
        verified = _status_id(url) in cited
        if cited and not verified:
            continue
        seen.add(url)
        posts.append(
            {
                "source": "x",
                "source_url": url,
                "text": text[:4000],
                "title": None,
                "display_name": (item.get("author") or url.split("/")[3]).lstrip("@")[:80],
                "created_at": item.get("posted_at"),
                "location_label": item.get("location") or None,
                "product_name": product[:200],
                "brand": (item.get("brand") or None),
                "category": normalize_category(item.get("category")),
                "issue": item.get("issue") or focus,
                "verified_url": verified,
            }
        )
    return posts[:limit]
