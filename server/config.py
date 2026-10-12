"""Settings, read once from environment variables.

On Replit, REPL_ID is always set, so the app defaults to Replit Auth and Replit
Object Storage there, and to a dev login and a local folder everywhere else.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{ROOT_DIR / 'data' / 'app.db'}"
    # Replit provides postgresql://...; SQLAlchemy needs the psycopg 3 driver named.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class Settings:
    on_replit: bool
    is_deployment: bool
    database_url: str
    auth_mode: str  # "replit" or "dev"
    session_secret: str
    oidc_issuer: str
    oidc_client_id: str
    storage_mode: str  # "replit" or "local"
    storage_bucket: str | None
    local_storage_dir: Path
    max_urls_per_run: int
    max_runs_per_day: int
    max_sites_per_user: int
    crawl_concurrency: int
    crawl_delay_ms: int


@lru_cache
def get_settings() -> Settings:
    on_replit = bool(os.environ.get("REPL_ID"))
    is_deployment = os.environ.get("REPLIT_DEPLOYMENT") == "1"
    auth_mode = os.environ.get("AUTH_MODE") or ("replit" if on_replit else "dev")
    if auth_mode == "dev" and is_deployment:
        raise RuntimeError("AUTH_MODE=dev is not allowed in a deployment")

    # Empty means "generate one and keep it in the database" (see repo.get_or_create_secret).
    session_secret = os.environ.get("SESSION_SECRET", "")

    return Settings(
        on_replit=on_replit,
        is_deployment=is_deployment,
        database_url=_database_url(),
        auth_mode=auth_mode,
        session_secret=session_secret,
        oidc_issuer=os.environ.get("ISSUER_URL", "https://replit.com/oidc"),
        oidc_client_id=os.environ.get("OIDC_CLIENT_ID") or os.environ.get("REPL_ID", ""),
        storage_mode=os.environ.get("STORAGE_MODE") or ("replit" if on_replit else "local"),
        storage_bucket=os.environ.get("STORAGE_BUCKET_ID") or None,
        local_storage_dir=Path(os.environ.get("LOCAL_STORAGE_DIR") or ROOT_DIR / "data" / "storage"),
        max_urls_per_run=_int("MAX_URLS_PER_RUN", 500),
        max_runs_per_day=_int("MAX_RUNS_PER_DAY", 10),
        max_sites_per_user=_int("MAX_SITES_PER_USER", 10),
        crawl_concurrency=_int("CRAWL_CONCURRENCY", 4),
        crawl_delay_ms=_int("CRAWL_DELAY_MS", 250),
    )
