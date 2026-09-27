from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
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
_ensure_sqlite_path(settings.resolved_database_url)

connect_args: dict = {}
engine_kwargs: dict = {"future": True}
if settings.is_sqlite:
    connect_args = {"check_same_thread": False}
else:
    # Remote Postgres (Supabase): keep a small warm pool and fail fast on dead sockets.
    # prepare_threshold=None avoids DuplicatePreparedStatement on transaction poolers.
    connect_args = {"connect_timeout": 10, "prepare_threshold": None}
    engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_size": 5,
            "max_overflow": 5,
            "pool_recycle": 280,
        }
    )

engine = create_engine(
    settings.resolved_database_url,
    connect_args=connect_args,
    **engine_kwargs,
)

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


def ensure_schema() -> None:
    """Add auth columns / like uniqueness on existing SQLite files."""
    tables = inspect(engine).get_table_names()
    additions = {
        "reports": ["user_sub"],
        "posts": ["user_sub"],
        "comments": ["user_sub"],
        "likes": ["user_sub"],
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in tables:
                continue
            existing = _table_columns(conn, table)
            for column in columns:
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(64)"))
        if "likes" in tables:
            _migrate_likes_unique(conn)


def _table_columns(conn, table: str) -> set[str]:
    if settings.is_sqlite:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    return {col["name"] for col in inspect(engine).get_columns(table)}


def _unique_column_sets(conn, table: str) -> list[set[str]]:
    if not settings.is_sqlite:
        return [set(item.get("column_names") or []) for item in inspect(engine).get_unique_constraints(table)]
    sets: list[set[str]] = []
    for row in conn.execute(text(f"PRAGMA index_list({table})")):
        if not row[2]:
            continue
        cols = {info[2] for info in conn.execute(text(f'PRAGMA index_info("{row[1]}")'))}
        sets.append(cols)
    return sets


def _migrate_likes_unique(conn) -> None:
    columns = _table_columns(conn, "likes")
    uniques = _unique_column_sets(conn, "likes")
    legacy = {"post_id", "display_name"} in uniques
    if not legacy and "user_sub" in columns:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_likes_post_user ON likes (post_id, user_sub)"))
        return
    conn.execute(text("DROP TABLE IF EXISTS likes_auth_new"))
    conn.execute(
        text(
            """
            CREATE TABLE likes_auth_new (
                id INTEGER PRIMARY KEY,
                post_id INTEGER NOT NULL,
                display_name VARCHAR(80) NOT NULL,
                user_sub VARCHAR(64),
                created_at DATETIME,
                FOREIGN KEY(post_id) REFERENCES posts(id)
            )
            """
        )
    )
    user_sub_select = "user_sub" if "user_sub" in columns else "NULL"
    conn.execute(
        text(
            f"""
            INSERT INTO likes_auth_new (id, post_id, display_name, user_sub, created_at)
            SELECT id, post_id, display_name, {user_sub_select}, created_at FROM likes
            """
        )
    )
    conn.execute(text("DROP TABLE likes"))
    conn.execute(text("ALTER TABLE likes_auth_new RENAME TO likes"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_likes_post_id ON likes (post_id)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_likes_post_user ON likes (post_id, user_sub)"))
