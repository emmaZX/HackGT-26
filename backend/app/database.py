from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_path(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    raw = url.split("///", 1)[-1]
    path = Path(raw)
    if path.parent and str(path.parent) not in {".", ""}:
        path.parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()
_ensure_sqlite_path(settings.database_url)

connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
