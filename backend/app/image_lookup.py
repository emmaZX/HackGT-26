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

Env:
  IMAGE_LOOKUP_LIMIT  max products to look up per startup (default 30, 0 disables)
"""

from __future__ import annotations

import logging
import os
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


class RateLimited(Exception):
    pass


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


def find_image(product: Product) -> str | None:
    full, name_only = _terms(product)
    if len(name_only) < 4:
        return None
    if _is_food(product):
        found = open_food_facts(full)
        time.sleep(6.5)  # Open Food Facts allows ~10 searches per minute
        if found:
            return found
    for query in dict.fromkeys([full, name_only]):  # branded first, then generic
        found = openverse(query)
        time.sleep(1.5)
        if found:
            return found
    return None


def start_image_lookup_background() -> None:
    limit = int(os.getenv("IMAGE_LOOKUP_LIMIT", "30") or 0)
    if limit <= 0:
        return

    def worker() -> None:
        time.sleep(20)  # after the CPSC sync, which fills official photos first
        found = 0
        with SessionLocal() as db:
            products = db.query(Product).filter(Product.image_url.is_(None)).limit(limit).all()
            for product in products:
                try:
                    image = find_image(product)
                    if image:
                        product.image_url = image
                        db.commit()
                        found += 1
                except RateLimited as exc:
                    logger.warning("Image lookup rate-limited by %s; stopping until next restart", exc)
                    break
                except Exception:
                    logger.exception("Image lookup failed for %s", product.slug)
                    db.rollback()
        logger.warning("Image lookup done: %s of %s products got an image", found, len(products))

    threading.Thread(target=worker, name="image-lookup", daemon=True).start()