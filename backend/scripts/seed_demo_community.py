#!/usr/bin/env python3
"""
Seed demo community life for snapshot mode.

Adds location-tagged community reports (map dots), neighbor posts, comments, and likes
for every Priority Foods card — Atlanta-weighted so the home map looks alive.
Idempotent: keyed on source_id / body markers so re-runs don't duplicate.
"""

from __future__ import annotations

import hashlib
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.feed_cache import invalidate  # noqa: E402
from app.models import Comment, Like, Post, Product, Report  # noqa: E402
from app.services import list_feed  # noqa: E402

# Must match frontend/src/lib/identity.ts labels exactly (map only plots known cities).
CITIES = [
    {"label": "Atlanta", "lat": 33.75, "lng": -84.39, "weight": 10},
    {"label": "Marietta", "lat": 33.95, "lng": -84.55, "weight": 3},
    {"label": "Decatur", "lat": 33.77, "lng": -84.3, "weight": 3},
    {"label": "Chicago", "lat": 41.88, "lng": -87.63, "weight": 2},
    {"label": "Boston", "lat": 42.36, "lng": -71.06, "weight": 1},
    {"label": "Austin", "lat": 30.27, "lng": -97.74, "weight": 1},
    {"label": "Seattle", "lat": 47.61, "lng": -122.33, "weight": 1},
]

NAMES = [
    "Alex", "Sam", "Jordan", "Riley", "Casey", "Maya", "Chris", "Taylor",
    "Priya", "Devon", "Nina", "Omar", "Jules", "Kai", "Morgan", "Avery",
]

WARNINGS = [
    "Heads up — I bought {name} at {store} and got really sick overnight. Anyone else in {city}?",
    "Warning: {name} from {brand}. Threw up ~6 hours after eating. Lot looked fine.",
    "Saw a recall notice online for {name}. Checking my fridge now. {city} Kroger still had it on the shelf yesterday.",
    "If you have {name} ({brand}), maybe don't eat it until this clears. Neighbor two doors down had the same issue.",
    "Public health alert vibes on {name}. Sharing so others in {city} can compare notes.",
]

COMMENTS_ON_WARN = [
    "Same here — ate it Tuesday, wrecked by Wednesday morning.",
    "Thanks for posting. Tossed ours just now.",
    "Which store? Trying to figure out if my pack is from the same batch.",
    "Ugh. We had mild symptoms too. Glad this page exists.",
    "Linking this in our building Slack. Appreciate the heads-up.",
]

QUESTIONS = [
    "Has anyone in {city} seen {name} pulled from shelves yet?",
    "Is the {brand} {name} recall only certain lots, or everything?",
    "Any update from USDA/FDA beyond what's already on this page?",
]

REPLIES = [
    "Still on the shelf at my store as of this morning.",
    "Mine had a sell-by from last week — already gone.",
    "Official notice is linked above if you scroll.",
]

SUPPORT = [
    "Bookmarking this. The early chatter is why I check here first.",
    "Glad people are documenting this instead of just rage-tweeting.",
    "We stopped buying {brand} for now. Better safe.",
]


STORES = ["Kroger", "Publix", "Walmart", "Costco", "Trader Joe's", "Aldi", "Sprouts"]


def _pick_city(rng: random.Random) -> dict:
    weights = [c["weight"] for c in CITIES]
    return rng.choices(CITIES, weights=weights, k=1)[0]


def _jitter(lat: float, lng: float, rng: random.Random) -> tuple[float, float]:
    return (round(lat + rng.uniform(-0.04, 0.04), 4), round(lng + rng.uniform(-0.05, 0.05), 4))


def _marker(product_id: int, kind: str, n: int) -> str:
    return f"demo-seed:{product_id}:{kind}:{n}"


def seed_product(db, product: Product, rng: random.Random) -> dict:
    brand = product.brand if product.brand and product.brand != "Unknown" else "this brand"
    name = product.name or "this product"
    added = {"reports": 0, "posts": 0, "comments": 0, "likes": 0}

    # 2–4 geo-tagged community reports (drive the map + stats)
    n_reports = rng.randint(2, 4)
    for i in range(n_reports):
        sid = _marker(product.id, "report", i)
        if db.query(Report).filter(Report.source_id == sid).first():
            continue
        city = _pick_city(rng)
        lat, lng = _jitter(city["lat"], city["lng"], rng)
        hours_ago = rng.randint(4, 72)
        body = rng.choice(WARNINGS).format(name=name, brand=brand, city=city["label"], store=rng.choice(STORES))
        db.add(
            Report(
                product_id=product.id,
                source="community",
                source_id=sid,
                source_url=None,
                title=f"Neighbor note — {city['label']}",
                text=body,
                excerpt=body[:220],
                created_at=datetime.utcnow() - timedelta(hours=hours_ago),
                incident_date=datetime.utcnow() - timedelta(hours=hours_ago + rng.randint(0, 12)),
                latitude=lat,
                longitude=lng,
                location_label=city["label"],
                location_precision="city",
                location_source="demo",
                is_user_generated=True,
                display_name=rng.choice(NAMES),
                independence_weight=1.0,
                extra_json='{"confidence":0.7,"method":"user"}',
            )
        )
        added["reports"] += 1

    # 2–3 posts with comments + likes
    n_posts = rng.randint(2, 3)
    for i in range(n_posts):
        marker = f"[demo-seed {product.id}/{i}]"
        if db.query(Post).filter(Post.product_id == product.id, Post.body.contains(marker)).first():
            continue
        city = _pick_city(rng)
        kind_roll = rng.random()
        if kind_roll < 0.45:
            body = rng.choice(WARNINGS).format(name=name, brand=brand, city=city["label"], store=rng.choice(STORES))
            reply_pool = COMMENTS_ON_WARN
        elif kind_roll < 0.75:
            body = rng.choice(QUESTIONS).format(name=name, brand=brand, city=city["label"])
            reply_pool = REPLIES
        else:
            body = rng.choice(SUPPORT).format(name=name, brand=brand, city=city["label"])
            reply_pool = COMMENTS_ON_WARN
        body = f"{body} {marker}"
        post = Post(
            product_id=product.id,
            display_name=rng.choice(NAMES),
            body=body,
            location_label=city["label"],
            created_at=datetime.utcnow() - timedelta(hours=rng.randint(1, 96)),
        )
        db.add(post)
        db.flush()
        added["posts"] += 1

        for j in range(rng.randint(1, 3)):
            db.add(
                Comment(
                    post_id=post.id,
                    display_name=rng.choice(NAMES),
                    body=rng.choice(reply_pool),
                    created_at=datetime.utcnow() - timedelta(hours=rng.randint(0, 48)),
                )
            )
            added["comments"] += 1

        liked = set()
        for j in range(rng.randint(2, 6)):
            who = rng.choice(NAMES)
            if who in liked:
                continue
            liked.add(who)
            db.add(Like(post_id=post.id, display_name=who, user_sub=f"demo-{hashlib.md5(who.encode()).hexdigest()[:12]}"))
            added["likes"] += 1

    return added


def main() -> None:
    rng = random.Random(26)  # stable demo
    totals = {"reports": 0, "posts": 0, "comments": 0, "likes": 0, "products": 0}

    # Collect slugs in a throwaway session so feed_cards' product.reports attach
    # doesn't leave orphaned Report rows in the identity map.
    with SessionLocal() as db:
        feed = list_feed(db, city="Atlanta")
        slugs: list[str] = []
        for key in ("priority_foods", "important", "official", "unofficial", "caers_spikes", "nearby"):
            for card in feed.get(key) or []:
                if card.get("slug"):
                    slugs.append(card["slug"])
        seen: set[str] = set()
        ordered = []
        for s in slugs:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        ordered = ordered[:28]

    with SessionLocal() as db:
        for slug in ordered:
            product = db.query(Product).filter(Product.slug == slug).one_or_none()
            if not product:
                continue
            added = seed_product(db, product, rng)
            totals["products"] += 1
            for k in ("reports", "posts", "comments", "likes"):
                totals[k] += added[k]
        db.commit()
    invalidate()
    print(totals)


if __name__ == "__main__":
    main()
