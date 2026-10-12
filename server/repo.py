"""All database reads and writes. Every user-facing query filters by user_id."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, insert, select, update

from .db import app_secrets, crawl_runs, get_engine, issues, sites, url_results, users


def now() -> datetime:
    return datetime.now(timezone.utc)


def _row(r) -> dict | None:
    return dict(r._mapping) if r is not None else None


# App secrets

def get_or_create_secret(key: str) -> str:
    """Returns a random secret stored in the database, creating it on first use.

    Lets the app run without anyone pasting a SESSION_SECRET into Replit Secrets.
    """
    import secrets

    from sqlalchemy.exc import IntegrityError

    with get_engine().begin() as c:
        value = c.execute(select(app_secrets.c.value).where(app_secrets.c.key == key)).scalar()
        if value:
            return value
    try:
        with get_engine().begin() as c:
            value = secrets.token_urlsafe(48)
            c.execute(insert(app_secrets).values(key=key, value=value))
            return value
    except IntegrityError:  # another instance created it first
        with get_engine().begin() as c:
            return c.execute(select(app_secrets.c.value).where(app_secrets.c.key == key)).scalar_one()


# Users

def upsert_user(user_id: str, email: str | None, name: str | None) -> None:
    with get_engine().begin() as c:
        exists = c.execute(select(users.c.id).where(users.c.id == user_id)).first()
        if exists:
            c.execute(update(users).where(users.c.id == user_id).values(email=email, name=name))
        else:
            c.execute(insert(users).values(id=user_id, email=email, name=name))


# Sites

def _last_run_subquery():
    return (
        select(crawl_runs.c.site_id, func.max(crawl_runs.c.id).label("last_run_id"))
        .group_by(crawl_runs.c.site_id)
        .subquery()
    )


def list_sites(user_id: str) -> list[dict]:
    last = _last_run_subquery()
    q = (
        select(
            sites,
            crawl_runs.c.id.label("last_run_id"),
            crawl_runs.c.status.label("last_run_status"),
            crawl_runs.c.finished_at.label("last_run_finished_at"),
            crawl_runs.c.errors.label("last_run_errors"),
            crawl_runs.c.warnings.label("last_run_warnings"),
            crawl_runs.c.urls_checked.label("last_run_urls_checked"),
        )
        .select_from(
            sites.outerjoin(last, last.c.site_id == sites.c.id).outerjoin(
                crawl_runs, crawl_runs.c.id == last.c.last_run_id
            )
        )
        .where(sites.c.user_id == user_id)
        .order_by(sites.c.created_at.desc(), sites.c.id.desc())
    )
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def count_sites(user_id: str) -> int:
    with get_engine().connect() as c:
        return c.execute(select(func.count()).select_from(sites).where(sites.c.user_id == user_id)).scalar_one()


def add_site(user_id: str, root_url: str) -> dict:
    with get_engine().begin() as c:
        existing = c.execute(
            select(sites).where(and_(sites.c.user_id == user_id, sites.c.root_url == root_url))
        ).first()
        if existing:
            return _row(existing)
        site_id = c.execute(
            insert(sites).values(user_id=user_id, root_url=root_url, weekly_check=True).returning(sites.c.id)
        ).scalar_one()
        return _row(c.execute(select(sites).where(sites.c.id == site_id)).first())


def get_site(user_id: str, site_id: int) -> dict | None:
    with get_engine().connect() as c:
        return _row(
            c.execute(select(sites).where(and_(sites.c.id == site_id, sites.c.user_id == user_id))).first()
        )


def delete_site(user_id: str, site_id: int) -> list[str]:
    """Deletes the site and its runs; returns report keys so storage can be cleaned up."""
    with get_engine().begin() as c:
        keys = [
            k
            for (k,) in c.execute(
                select(crawl_runs.c.report_key)
                .select_from(crawl_runs.join(sites, sites.c.id == crawl_runs.c.site_id))
                .where(and_(sites.c.id == site_id, sites.c.user_id == user_id))
            )
            if k
        ]
        run_ids = select(crawl_runs.c.id).where(crawl_runs.c.site_id == site_id)
        # Explicit deletes so SQLite without FK enforcement behaves the same as Postgres.
        c.execute(delete(issues).where(issues.c.run_id.in_(run_ids)))
        c.execute(delete(url_results).where(url_results.c.run_id.in_(run_ids)))
        c.execute(delete(crawl_runs).where(crawl_runs.c.site_id == site_id))
        c.execute(delete(sites).where(and_(sites.c.id == site_id, sites.c.user_id == user_id)))
        return keys


def set_weekly(user_id: str, site_id: int, weekly: bool) -> None:
    with get_engine().begin() as c:
        c.execute(
            update(sites)
            .where(and_(sites.c.id == site_id, sites.c.user_id == user_id))
            .values(weekly_check=weekly)
        )


def sites_for_weekly() -> list[dict]:
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(select(sites).where(sites.c.weekly_check.is_(True)))]


# Runs

def create_run(site_id: int, trigger: str) -> int:
    with get_engine().begin() as c:
        return c.execute(
            insert(crawl_runs)
            .values(site_id=site_id, trigger=trigger, status="queued", created_at=now())
            .returning(crawl_runs.c.id)
        ).scalar_one()


def has_active_run(user_id: str) -> bool:
    q = (
        select(func.count())
        .select_from(crawl_runs.join(sites, sites.c.id == crawl_runs.c.site_id))
        .where(and_(sites.c.user_id == user_id, crawl_runs.c.status.in_(["queued", "running"])))
    )
    with get_engine().connect() as c:
        return c.execute(q).scalar_one() > 0


def count_manual_runs_since(user_id: str, since: datetime) -> int:
    q = (
        select(func.count())
        .select_from(crawl_runs.join(sites, sites.c.id == crawl_runs.c.site_id))
        .where(
            and_(
                sites.c.user_id == user_id,
                crawl_runs.c.trigger == "manual",
                crawl_runs.c.created_at >= since,
            )
        )
    )
    with get_engine().connect() as c:
        return c.execute(q).scalar_one()


def manual_runs_last_24h(user_id: str) -> int:
    return count_manual_runs_since(user_id, now() - timedelta(hours=24))


def get_run(user_id: str, run_id: int) -> dict | None:
    q = (
        select(crawl_runs, sites.c.root_url, sites.c.user_id)
        .select_from(crawl_runs.join(sites, sites.c.id == crawl_runs.c.site_id))
        .where(and_(crawl_runs.c.id == run_id, sites.c.user_id == user_id))
    )
    with get_engine().connect() as c:
        return _row(c.execute(q).first())


def get_run_internal(run_id: int) -> dict | None:
    q = (
        select(crawl_runs, sites.c.root_url, sites.c.user_id)
        .select_from(crawl_runs.join(sites, sites.c.id == crawl_runs.c.site_id))
        .where(crawl_runs.c.id == run_id)
    )
    with get_engine().connect() as c:
        return _row(c.execute(q).first())


def list_runs(user_id: str, site_id: int, limit: int = 20) -> list[dict]:
    q = (
        select(crawl_runs)
        .select_from(crawl_runs.join(sites, sites.c.id == crawl_runs.c.site_id))
        .where(and_(sites.c.id == site_id, sites.c.user_id == user_id))
        .order_by(crawl_runs.c.id.desc())
        .limit(limit)
    )
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def update_run(run_id: int, **values) -> None:
    with get_engine().begin() as c:
        c.execute(update(crawl_runs).where(crawl_runs.c.id == run_id).values(**values))


def expire_stale_runs(max_age_minutes: int = 30) -> int:
    """A run takes a few minutes; one still open after max_age was killed by a restart.

    Age-based rather than "everything open" so a new web instance never fails a run
    that another instance or the weekly job is still working on.
    """
    cutoff = now() - timedelta(minutes=max_age_minutes)
    with get_engine().begin() as c:
        return c.execute(
            update(crawl_runs)
            .where(and_(crawl_runs.c.status.in_(["queued", "running"]), crawl_runs.c.created_at < cutoff))
            .values(status="failed", finished_at=now(), error_message="Interrupted (the server restarted)")
        ).rowcount


def save_results(run_id: int, url_rows: list[dict], issue_rows: list[dict]) -> None:
    with get_engine().begin() as c:
        if url_rows:
            c.execute(insert(url_results), [{**r, "run_id": run_id} for r in url_rows])
        if issue_rows:
            c.execute(insert(issues), [{**r, "run_id": run_id} for r in issue_rows])


def run_issues(run_id: int, severity: str | None = None) -> list[dict]:
    q = select(issues).where(issues.c.run_id == run_id)
    if severity:
        q = q.where(issues.c.severity == severity)
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q.order_by(issues.c.id))]


def run_urls(run_id: int, offset: int, limit: int) -> tuple[list[dict], int]:
    with get_engine().connect() as c:
        total = c.execute(
            select(func.count()).select_from(url_results).where(url_results.c.run_id == run_id)
        ).scalar_one()
        rows = c.execute(
            select(url_results)
            .where(url_results.c.run_id == run_id)
            .order_by(url_results.c.id)
            .offset(offset)
            .limit(limit)
        )
        return [dict(r._mapping) for r in rows], total
