#!/usr/bin/env python3
import json
import urllib.request

from app.database import SessionLocal
from app.bootstrap import scrub_catalog_quality, purge_fake_community_data
from app.config import get_settings
from app.services import list_feed
from app.pipeline.evidence_schema import text_has_ancient_year

get_settings.cache_clear()
with SessionLocal() as db:
    print("fake", purge_fake_community_data(db))
    print("scrub", scrub_catalog_quality(db))
    db.commit()

with SessionLocal() as db:
    feed = list_feed(db)
    print({k: len(feed[k]) for k in ["official", "caers_spikes", "unofficial", "important"]})
    for label in ["official", "unofficial", "caers_spikes"]:
        print(f"=== {label} ===")
        for c in feed[label][:10]:
            print(f"  {c['brand']} · {c['name']}")

try:
    data = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/feed", timeout=5))
    print("live unofficial", len(data.get("unofficial") or []))
except Exception as exc:
    print("live api", exc)

# Assert no ancient years in unofficial names/summaries
with SessionLocal() as db:
    feed = list_feed(db)
    for c in feed["unofficial"]:
        blob = f"{c.get('brand')} {c.get('name')} {c.get('summary')}"
        assert not text_has_ancient_year(blob), blob
print("OK")
