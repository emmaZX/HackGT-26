#!/usr/bin/env python3
import logging

logging.basicConfig(level=logging.INFO)

from app.database import SessionLocal
from app.bootstrap import _overlay_fsis_recalls
from app.services import list_feed


def main() -> None:
    with SessionLocal() as db:
        _overlay_fsis_recalls(db, limit=20)
        db.commit()
    with SessionLocal() as db:
        feed = list_feed(db)
        print(
            "official",
            len(feed["official"]),
            "caers",
            len(feed["caers_spikes"]),
            "unofficial",
            len(feed["unofficial"]),
        )
        fsis = [
            c
            for c in feed["official"]
            if "FSIS"
            in str(((c.get("signal") or {}).get("official_recall") or {}).get("agency") or "")
            or "fsis-" in c["slug"]
        ]
        print("fsis", len(fsis), [c["slug"] for c in fsis[:5]])
        print(
            "outbreak",
            sum(1 for c in feed["official"] if c["signal"].get("outbreak")),
        )
        for c in feed["caers_spikes"][:3]:
            print("spike", c["slug"], c["tags"])
            assert "FDA RECALL" not in c["tags"]
    print("VERIFY_FEED_OK")


if __name__ == "__main__":
    main()
