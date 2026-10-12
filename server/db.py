"""Database schema (SQLAlchemy Core) and engine.

The same tables run on Replit PostgreSQL in production and SQLite locally.
"""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
)
from sqlalchemy.engine import Engine

# SQLite only auto-increments INTEGER PRIMARY KEY columns.
ID = BigInteger().with_variant(Integer, "sqlite")
TS = DateTime(timezone=True)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Text, primary_key=True),  # Replit Auth "sub"
    Column("email", Text),
    Column("name", Text),
    Column("created_at", TS, server_default=func.now()),
)

sites = Table(
    "sites",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("user_id", Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("root_url", Text, nullable=False),
    Column("weekly_check", Boolean, nullable=False, default=True),
    Column("created_at", TS, server_default=func.now()),
    UniqueConstraint("user_id", "root_url"),
)

crawl_runs = Table(
    "crawl_runs",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("site_id", ID, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column("trigger", Text, nullable=False),  # manual | scheduled
    Column("status", Text, nullable=False),  # queued | running | done | failed
    Column("created_at", TS, server_default=func.now()),
    Column("started_at", TS),
    Column("finished_at", TS),
    Column("origin", Text),
    Column("urls_found", Integer, nullable=False, default=0),
    Column("urls_checked", Integer, nullable=False, default=0),
    Column("errors", Integer, nullable=False, default=0),
    Column("warnings", Integer, nullable=False, default=0),
    Column("notices", Integer, nullable=False, default=0),
    Column("truncated", Boolean, nullable=False, default=False),
    Column("report_key", Text),
    Column("error_message", Text),
)

url_results = Table(
    "url_results",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("run_id", ID, ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False),
    Column("url", Text, nullable=False),
    Column("sitemap", Text),
    Column("lastmod", Text),
    Column("status_code", Integer),
    Column("final_url", Text),
    Column("redirect_chain", JSON),  # [{"url": ..., "status": ...}, ...]
    Column("meta_robots", Text),
    Column("x_robots_tag", Text),
    Column("canonical", Text),
    Column("blocked_for_googlebot", Boolean),
    Column("fetch_ms", Integer),
    Column("error", Text),
)

issues = Table(
    "issues",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("run_id", ID, ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False),
    Column("url", Text),  # null for site-level issues
    Column("code", Text, nullable=False),
    Column("severity", Text, nullable=False),  # error | warning | info
    Column("detail", Text),
)

app_secrets = Table(
    "app_secrets",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

Index("ix_sites_user", sites.c.user_id)
Index("ix_runs_site", crawl_runs.c.site_id)
Index("ix_url_results_run", url_results.c.run_id)
Index("ix_issues_run", issues.c.run_id, issues.c.severity)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        from .config import get_settings

        _engine = make_engine(get_settings().database_url)
    return _engine


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        from pathlib import Path

        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a throwaway database."""
    global _engine
    _engine = engine


def init_db() -> None:
    metadata.create_all(get_engine())
