#!/usr/bin/env python3
from app.pipeline.product_identity import simplify_food_item
from app.database import SessionLocal
from app.bootstrap import polish_catalog_titles, _overlay_outbreaks, _overlay_fsis_recalls
from app.config import get_settings
from app.models import Product
from app.services import list_feed

samples = [
    (
        "FSIS Issues Public Health Alert for Chicken Product Due to Possible Salmonella Contamination",
        "FSIS Issues Public Health Alert for Chicken Product Due to Possible Salmonella Contamination",
    ),
    (
        "['Plainville Farms']",
        "FSIS Issues Public Health Alert for Raw Ground Turkey Products Due to Possible Foreign Matter Contamination",
    ),
    (
        "Star Meat Delivery Inc.",
        "Star Meat Delivery Inc. Recalls Raw Pork, Beef, and Goat Products Due to Possible Contamination",
    ),
    ("FDA Outbreak Watch", "E. coli O26:H11 — Raw Milk Cheese"),
    ("Exemption", "4"),
]
for brand, name in samples:
    print(simplify_food_item(brand=brand, name=name))

get_settings.cache_clear()
with SessionLocal() as db:
    print("polished", polish_catalog_titles(db))
    _overlay_outbreaks(db, limit=30)
    db.commit()

with SessionLocal() as db:
    for p in db.query(Product).filter(Product.slug.like("fsis-%")).limit(8):
        print("FSIS", p.brand, "|", p.name)
    for p in db.query(Product).filter(Product.slug.like("outbreak-%")).limit(5):
        print("OUT", p.brand, "|", p.name)
    feed = list_feed(db)
    print(
        {
            k: len(feed.get(k) or [])
            for k in ("official", "caers_spikes", "unofficial", "important")
        }
    )
    for c in (feed.get("official") or [])[:6]:
        print(" ", c["brand"], "|", c["name"])
    for c in (feed.get("caers_spikes") or [])[:6]:
        print(" C", c["brand"], "|", c["name"])
