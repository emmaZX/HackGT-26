#!/usr/bin/env python3
"""Backfill official-notice reports + polish titles so product pages show stats ≥ 1."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bootstrap import backfill_official_notice_reports, polish_catalog_titles  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.feed_cache import invalidate  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        notices = backfill_official_notice_reports(db)
        polished = polish_catalog_titles(db)
        db.commit()
    invalidate()
    print(f"official_notice_reports_added={notices} titles_polished={polished}")


if __name__ == "__main__":
    main()
