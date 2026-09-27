#!/usr/bin/env python3
from app.database import SessionLocal, Base, engine, ensure_schema
from app.bootstrap import scrub_catalog_quality
from app.config import get_settings
from app.services import list_feed
from app.models import Product, Recall

get_settings.cache_clear()
Base.metadata.create_all(bind=engine)
ensure_schema()

with SessionLocal() as db:
    print(scrub_catalog_quality(db))
    db.commit()

with SessionLocal() as db:
    print("products", db.query(Product).count(), "recalls", db.query(Recall).count())
    feed = list_feed(db)
    print({k: len(feed[k]) for k in ["official", "caers_spikes", "unofficial", "important"]})
    print("--- official ---")
    for c in feed["official"][:15]:
        print(f"  {c['brand']} · {c['name']}")
    print("--- important ---")
    for c in feed["important"][:10]:
        print(f"  {c['brand']} · {c['name']}")
    for c in feed["official"] + feed["caers_spikes"] + feed["unofficial"]:
        assert "unidentified" not in c["name"].lower(), c["name"]
        assert "ineligible" not in c["name"].lower(), c["name"]
        assert "without the benefit" not in c["name"].lower(), c["name"]
        assert len(c["name"]) <= 40, c["name"]
    print("QUALITY_OK")
