"""FastAPI app: JSON API under /api, login under /auth, and the built React app."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import repo
from .auth import current_user, router as auth_router
from .config import ROOT_DIR, get_settings
from .crawler.checks import ISSUE_INFO
from .crawler.fetch import BlockedURL, assert_public_url, check_url_shape
from .crawler.run import default_fetcher, execute_run
from .db import init_db
from .storage import get_store

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per crawled URL is too noisy
log = logging.getLogger(__name__)

DIST_DIR = ROOT_DIR / "web" / "dist"
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


class SiteIn(BaseModel):
    root_url: str


class SitePatch(BaseModel):
    weekly_check: bool


def normalize_root(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise BlockedURL("Enter a website address")
    if "://" not in raw:
        raw = "https://" + raw
    host, port = check_url_shape(raw)
    scheme = urlsplit(raw).scheme
    return f"{scheme}://{host}"


def _public_run(run: dict) -> dict:
    run = dict(run)
    run.pop("user_id", None)
    run.pop("report_key", None)
    return run


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        failed = repo.expire_stale_runs()
        if failed:
            log.info("Marked %s interrupted runs as failed", failed)
        yield

    app = FastAPI(title="Index Health Monitor", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.fetcher_factory = default_fetcher
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.on_replit,
        max_age=14 * 24 * 3600,
    )
    app.include_router(auth_router)

    def owned_run(run_id: int, user: dict) -> dict:
        run = repo.get_run(user["id"], run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        return run

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return {**user, "auth_mode": settings.auth_mode}

    @app.get("/api/sites")
    def list_sites(user: dict = Depends(current_user)):
        return repo.list_sites(user["id"])

    @app.post("/api/sites", status_code=201)
    async def add_site(body: SiteIn, user: dict = Depends(current_user)):
        try:
            root = normalize_root(body.root_url)
            await assert_public_url(root)
        except BlockedURL as e:
            raise HTTPException(400, str(e))
        if repo.count_sites(user["id"]) >= settings.max_sites_per_user:
            raise HTTPException(400, f"You can add up to {settings.max_sites_per_user} sites")
        return repo.add_site(user["id"], root)

    @app.patch("/api/sites/{site_id}")
    def patch_site(site_id: int, body: SitePatch, user: dict = Depends(current_user)):
        if not repo.get_site(user["id"], site_id):
            raise HTTPException(404, "Site not found")
        repo.set_weekly(user["id"], site_id, body.weekly_check)
        return repo.get_site(user["id"], site_id)

    @app.delete("/api/sites/{site_id}", status_code=204)
    def delete_site(site_id: int, user: dict = Depends(current_user)):
        if not repo.get_site(user["id"], site_id):
            raise HTTPException(404, "Site not found")
        store = get_store(settings)
        for key in repo.delete_site(user["id"], site_id):
            try:
                store.delete(key)
            except Exception:
                log.warning("Could not delete report %s", key)
        return Response(status_code=204)

    @app.get("/api/sites/{site_id}")
    def get_site(site_id: int, user: dict = Depends(current_user)):
        site = repo.get_site(user["id"], site_id)
        if not site:
            raise HTTPException(404, "Site not found")
        return site

    @app.get("/api/sites/{site_id}/runs")
    def list_runs(site_id: int, user: dict = Depends(current_user)):
        if not repo.get_site(user["id"], site_id):
            raise HTTPException(404, "Site not found")
        return [_public_run(r) for r in repo.list_runs(user["id"], site_id)]

    @app.post("/api/sites/{site_id}/runs", status_code=202)
    def start_run(site_id: int, background: BackgroundTasks, user: dict = Depends(current_user)):
        if not repo.get_site(user["id"], site_id):
            raise HTTPException(404, "Site not found")
        repo.expire_stale_runs()
        if repo.has_active_run(user["id"]):
            raise HTTPException(409, "A check is already running. Wait for it to finish.")
        if repo.manual_runs_last_24h(user["id"]) >= settings.max_runs_per_day:
            raise HTTPException(429, f"Daily limit reached ({settings.max_runs_per_day} checks per 24 hours)")
        run_id = repo.create_run(site_id, "manual")
        background.add_task(execute_run, run_id, settings, get_store(settings), app.state.fetcher_factory)
        return {"id": run_id}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int, user: dict = Depends(current_user)):
        return _public_run(owned_run(run_id, user))

    @app.get("/api/runs/{run_id}/issues")
    def get_issues(
        run_id: int,
        severity: str | None = Query(None, pattern="^(error|warning|info)$"),
        user: dict = Depends(current_user),
    ):
        owned_run(run_id, user)
        groups: dict[str, dict] = {}
        for i in repo.run_issues(run_id, severity):
            sev, title, why = ISSUE_INFO.get(i["code"], (i["severity"], i["code"], ""))
            g = groups.setdefault(
                i["code"], {"code": i["code"], "severity": sev, "title": title, "why": why, "count": 0, "items": []}
            )
            g["count"] += 1
            g["items"].append({"url": i["url"], "detail": i["detail"]})
        return sorted(groups.values(), key=lambda g: (SEVERITY_ORDER.get(g["severity"], 9), -g["count"]))

    @app.get("/api/runs/{run_id}/urls")
    def get_urls(
        run_id: int,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=200),
        user: dict = Depends(current_user),
    ):
        owned_run(run_id, user)
        rows, total = repo.run_urls(run_id, (page - 1) * per_page, per_page)
        return {"items": rows, "total": total, "page": page, "per_page": per_page}

    @app.get("/api/runs/{run_id}/report.csv")
    def report_csv(run_id: int, user: dict = Depends(current_user)):
        run = owned_run(run_id, user)
        if not run.get("report_key"):
            raise HTTPException(404, "Report not ready")
        text = get_store(settings).get_text(run["report_key"])
        host = urlsplit(run["root_url"]).hostname or "site"
        return Response(
            text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="index-health-{host}-{run_id}.csv"'},
        )

    @app.get("/bot", response_class=HTMLResponse)
    def bot_page():
        return BOT_HTML

    @app.get("/api/{rest:path}")
    def api_not_found(rest: str):
        raise HTTPException(404, "Not found")

    # The React app (built into web/dist). Unknown paths fall back to index.html.
    if (DIST_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (DIST_DIR / path).resolve()
        if path and DIST_DIR.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        index = DIST_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse("<p>Front end not built. Run <code>npm run build</code> in /web.</p>", status_code=503)

    return app


BOT_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IndexHealthMonitor crawler</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;line-height:1.6;color:#0f172a}
code{background:#f1f5f9;padding:2px 6px;border-radius:4px}</style></head>
<body>
<h1>IndexHealthMonitor crawler</h1>
<p>User agent: <code>IndexHealthMonitor/1.0</code></p>
<p>This crawler checks a website's robots.txt, XML sitemaps and the pages they list, on behalf of the
site's owner, to find indexing problems such as broken URLs, redirects, noindex tags and canonical mismatches.</p>
<ul>
<li>It respects robots.txt rules for the <code>IndexHealthMonitor</code> user agent.</li>
<li>It makes at most 4 requests at a time with a pause between them, and checks at most 500 URLs per run.</li>
<li>It only reads page headers and the HTML &lt;head&gt;; it does not follow links or submit forms.</li>
</ul>
<p>To block it, add this to robots.txt:</p>
<pre><code>User-agent: IndexHealthMonitor
Disallow: /</code></pre>
</body></html>"""

app = create_app()
