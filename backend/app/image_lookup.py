"""
Free image lookup for products without an official photo. No API keys needed.

Order per product:
  1. Open Food Facts, for food products: real package photos (CC BY-SA).
  2. Openverse, for everything else (and food that Open Food Facts missed):
     openly licensed photos of the *kind* of item, labeled as illustrative.
  3. Nothing found: the frontend shows its text block.

Runs once in the background at startup, after the CPSC sync (which fills official photos
first). One image per product is saved in Product.image_url; nothing is searched per page view.

Photo credit rides in the URL fragment (…/photo.jpg#credit=…). Browsers ignore fragments when
loading images, and it avoids a schema change while the backend is being reworked.

Products with no match are remembered in data/image_lookup_checked.json, so each product is
searched once, ever. Delete that file to retry everything.

Env:
  IMAGE_LOOKUP_LIMIT  max products to look up per run (default 500, 0 disables)

Run it right away instead of waiting for a restart:
  .venv\\Scripts\\python run_image_lookup.py
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote

import httpx

from .database import SessionLocal
from .models import Product
from .openai_http import _verify

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "RecallMeMaybe/0.1 (HackGT 2026 student project)"}
OFF_SEARCH = "https://world.openfoodfacts.org/cgi/search.pl"
OPENVERSE_SEARCH = "https://api.openverse.org/v1/images/"
VAGUE_BRANDS = {"", "unknown", "search", "various"}
FOOD_WORDS = re.compile(
    r"food|salad|lettuce|romaine|melon|cantaloupe|chicken|meat|beef|pork|cheese|milk|egg|"
    r"snack|sprout|powder|produce|fruit|vegetable|juice|cereal|bread|nut|chocolate|formula",
    re.I,
)


CHECKED_FILE = Path(__file__).resolve().parents[1] / "data" / "image_lookup_checked.json"


class RateLimited(Exception):
    pass


def _load_checked() -> set[str]:
    try:
        return set(json.loads(CHECKED_FILE.read_text()))
    except Exception:
        return set()


def _save_checked(slugs: set[str]) -> None:
    CHECKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKED_FILE.write_text(json.dumps(sorted(slugs)))


def _terms(product: Product) -> tuple[str, str]:
    """(full query with brand, name-only query)"""
    brand = (product.brand or "").strip()
    name = re.sub(r"\s+", " ", (product.name or "").strip())
    if brand.lower() in VAGUE_BRANDS or name.lower().startswith(brand.lower()):
        return name, name
    return f"{brand} {name}", name


def _is_food(product: Product) -> bool:
    return bool(FOOD_WORDS.search(f"{product.category or ''} {product.name or ''}"))


def _with_credit(url: str, credit: str) -> str:
    return f"{url}#credit={quote(credit[:120])}"[:500]


def _get(url: str, params: dict) -> dict:
    response = httpx.get(url, params=params, headers=HEADERS, timeout=20, verify=_verify())
    if response.status_code == 429:
        raise RateLimited(url)
    response.raise_for_status()
    return response.json()


def open_food_facts(query: str) -> str | None:
    data = _get(
        OFF_SEARCH,
        {"search_terms": query, "search_simple": 1, "action": "process", "json": 1, "page_size": 5},
    )
    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
    for item in data.get("products") or []:
        image = item.get("image_front_url") or item.get("image_url")
        name = (item.get("product_name") or "").lower()
        # Require some overlap so a random product doesn't get picked
        if image and image.startswith("https://") and (not words or any(w in name for w in words)):
            return _with_credit(image, "Photo: Open Food Facts (CC BY-SA)")
    return None


def openverse(query: str) -> str | None:
    data = _get(OPENVERSE_SEARCH, {"q": query, "page_size": 5, "mature": "false"})
    for item in data.get("results") or []:
        thumb = item.get("thumbnail") or item.get("url")
        if not thumb or not thumb.startswith("https://"):
            continue
        creator = (item.get("creator") or "unknown").strip()[:40]
        license_ = f"CC {(item.get('license') or '').upper()} {item.get('license_version') or ''}".strip()
        if (item.get("license") or "").lower() in {"cc0", "pdm"}:
            license_ = "public domain"
        return _with_credit(thumb, f"Illustrative photo: {creator} ({license_})")
    return None


# Set when Open Food Facts errors (e.g. 503 when overloaded); skipped for the rest of the run
_off_unavailable = False


def find_image(product: Product) -> str | None:
    global _off_unavailable
    full, name_only = _terms(product)
    if len(name_only) < 4:
        return None
    if _is_food(product) and not _off_unavailable:
        try:
            found = open_food_facts(full)
            time.sleep(6.5)  # Open Food Facts allows ~10 searches per minute
            if found:
                return found
        except (RateLimited, httpx.HTTPError) as exc:
            _off_unavailable = True
            logger.warning("Open Food Facts unavailable (%s); using Openverse only for this run", str(exc)[:80])
    for query in dict.fromkeys([full, name_only]):  # branded first, then generic
        found = openverse(query)
        time.sleep(1.5)
        if found:
            return found
    return None


def run_image_lookup(limit: int | None = None) -> dict:
    """Look up images for every product that has none and hasn't been checked before."""
    global _off_unavailable
    _off_unavailable = False
    limit = limit if limit is not None else int(os.getenv("IMAGE_LOOKUP_LIMIT", "500") or 0)
    checked = _load_checked()
    found = missed = 0
    stopped = False
    with SessionLocal() as db:
        products = [
            p for p in db.query(Product).filter(Product.image_url.is_(None)).all() if p.slug not in checked
        ][:limit]
        for product in products:
            try:
                image = find_image(product)
            except RateLimited as exc:
                logger.warning("Image lookup rate-limited by %s; the rest will be tried next run", exc)
                stopped = True
                break
            except Exception as exc:
                logger.warning("Image lookup failed for %s: %s", product.slug, str(exc)[:120])
                continue  # network hiccup: not marked checked, so it's retried next run
            if image:
                product.image_url = image
                db.commit()
                found += 1
            elif _off_unavailable and _is_food(product):
                missed += 1  # Open Food Facts was down: retry this one next run
            else:
                checked.add(product.slug)  # no match: don't search this product again
                _save_checked(checked)
                missed += 1
    result = {"looked_up": found + missed, "found": found, "no_match": missed, "rate_limited": stopped}
    logger.warning("Image lookup done: %s", result)
    return result


def start_image_lookup_background() -> None:
    if int(os.getenv("IMAGE_LOOKUP_LIMIT", "500") or 0) <= 0:
        return

    def worker() -> None:
        time.sleep(20)  # after the CPSC sync, which fills official photos first
        run_image_lookup()

    threading.Thread(target=worker, name="image-lookup", daemon=True).start()