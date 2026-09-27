"""
Copy local SQLite catalog into Supabase/Postgres (shared demo DB).

Usage (from backend/, with venv on):
  1) Put the Supabase URI in DATABASE_URL (both root .env and backend/.env), e.g.
       DATABASE_URL=postgresql+psycopg://postgres.<ref>:<PASSWORD>@aws-0-....pooler.supabase.com:6543/postgres
  2) PYTHONPATH=. python migrate_sqlite_to_postgres.py

Safe to re-run only on an empty Postgres — it creates tables then copies rows.
Does not delete existing remote rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Local sqlite path (source of truth for the hackathon corpus).
SQLITE_URL = "sqlite:///" + str((Path(__file__).resolve().parent / "data" / "signal.db").as_posix())


def _normalize_pg(url: str) -> str:
    url = (url or "").strip().strip('"').strip("'")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def main() -> int:
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    dest = _normalize_pg(settings.resolved_database_url)
    if dest.startswith("sqlite"):
        print("DATABASE_URL is still SQLite. Set it to your Supabase Postgres URI first.")
        print("Dashboard → Project Settings → Database → Connection string (URI).")
        print("Prefer the Session pooler URI, then change the prefix to postgresql+psycopg://")
        return 1

    print("Source:", SQLITE_URL)
    print("Dest:  ", dest.split("@")[-1] if "@" in dest else dest[:40])

    from app.database import Base
    import app.models  # noqa: F401 — register tables

    src = create_engine(SQLITE_URL, future=True, connect_args={"check_same_thread": False})
    dst = create_engine(dest, future=True)

    print("Creating schema on Postgres…")
    Base.metadata.create_all(bind=dst)

    SrcSession = sessionmaker(bind=src, future=True)
    DstSession = sessionmaker(bind=dst, future=True)

    # Copy in FK-safe order (parents before children).
    table_order = [
        "issues",
        "products",
        "recalls",
        "reports",
        "report_issues",
        "embeddings",
        "posts",
        "comments",
        "likes",
        "discovery_runs",
    ]

    with SrcSession() as s_src, DstSession() as s_dst:
        for name in table_order:
            if name not in Base.metadata.tables:
                print(f"  skip missing model table {name}")
                continue
            table = Base.metadata.tables[name]
            rows = s_src.execute(text(f"SELECT * FROM {name}")).mappings().all()
            if not rows:
                print(f"  {name}: 0 rows")
                continue
            # Skip rows that already exist (by primary key id when present).
            existing_ids: set = set()
            if "id" in table.c:
                existing_ids = {
                    r[0] for r in s_dst.execute(text(f"SELECT id FROM {name}")).all()
                }
            inserted = 0
            for row in rows:
                data = dict(row)
                if "id" in data and data["id"] in existing_ids:
                    continue
                try:
                    s_dst.execute(table.insert().values(**data))
                    inserted += 1
                except Exception as exc:
                    s_dst.rollback()
                    print(f"  {name} row failed: {exc}")
                    continue
            s_dst.commit()
            print(f"  {name}: copied {inserted}/{len(rows)}")

        # Reset Postgres sequences so new inserts don't collide with copied ids.
        for name in table_order:
            if name not in Base.metadata.tables:
                continue
            table = Base.metadata.tables[name]
            if "id" not in table.c:
                continue
            s_dst.execute(
                text(
                    f"""
                    SELECT setval(
                      pg_get_serial_sequence('{name}', 'id'),
                      COALESCE((SELECT MAX(id) FROM {name}), 1),
                      true
                    )
                    """
                )
            )
        s_dst.commit()

    print("Done. Restart uvicorn so everyone hits Supabase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
