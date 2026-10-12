"""Runs one crawl from start to finish and stores the results."""

import asyncio
import logging
from typing import Callable

from .. import repo
from ..config import Settings
from ..reports import build_csv
from ..storage import ReportStore, report_key
from .checks import UrlResult, evaluate, severity_counts
from .fetch import SafeFetcher
from .page import parse_head
from .robots import load_robots
from .sitemaps import scan_sitemaps

log = logging.getLogger(__name__)

FetcherFactory = Callable[[Settings], SafeFetcher]


def default_fetcher(settings: Settings) -> SafeFetcher:
    return SafeFetcher(concurrency=settings.crawl_concurrency, delay_ms=settings.crawl_delay_ms)


def _is_html(resp) -> bool:
    ctype = resp.headers.get("content-type", "").lower()
    return 200 <= resp.status_code < 300 and ("text/html" in ctype or "application/xhtml" in ctype)


async def resolve_origin(fetcher: SafeFetcher, root_url: str) -> str:
    """Follows redirects on the home page so http→https and www moves are respected."""
    res = await fetcher.fetch(root_url.rstrip("/") + "/")
    final = res.final_url if not res.error else root_url
    scheme, rest = final.split("://", 1)
    return f"{scheme}://{rest.split('/', 1)[0]}"


async def check_url(fetcher: SafeFetcher, robots, entry) -> UrlResult:
    r = UrlResult(url=entry.loc, sitemap=entry.sitemap, lastmod=entry.lastmod)
    r.blocked_for_googlebot = not robots.allowed_for_googlebot(entry.loc)
    if not robots.allowed_for_us(entry.loc):
        r.skipped = True
        return r
    res = await fetcher.fetch(entry.loc, want_body=_is_html)
    r.fetch_ms = res.elapsed_ms
    r.final_url = res.final_url
    r.chain = [{"url": h.url, "status": h.status} for h in res.chain]
    if res.error:
        r.error = res.error
        return r
    r.status = res.status
    r.x_robots_tags = res.headers.get_list("x-robots-tag")
    if res.body is not None:
        r.is_html = True
        signals = parse_head(res.body, res.final_url)
        r.meta_robots = signals.meta_robots
        r.canonicals = signals.canonicals or []
    return r


def _url_row(r: UrlResult) -> dict:
    return {
        "url": r.url,
        "sitemap": r.sitemap,
        "lastmod": r.lastmod,
        "status_code": r.status,
        "final_url": r.final_url,
        "redirect_chain": r.chain,
        "meta_robots": r.meta_robots,
        "x_robots_tag": ", ".join(r.x_robots_tags) or None,
        "canonical": " | ".join(r.canonicals) or None,
        "blocked_for_googlebot": r.blocked_for_googlebot,
        "fetch_ms": r.fetch_ms,
        "error": r.error or ("Skipped: robots.txt blocks this crawler" if r.skipped else None),
    }


async def execute_run(
    run_id: int,
    settings: Settings,
    store: ReportStore,
    fetcher_factory: FetcherFactory = default_fetcher,
) -> None:
    run = await asyncio.to_thread(repo.get_run_internal, run_id)
    if run is None:
        return
    await asyncio.to_thread(repo.update_run, run_id, status="running", started_at=repo.now())
    try:
        async with fetcher_factory(settings) as fetcher:
            origin = await resolve_origin(fetcher, run["root_url"])
            robots = await load_robots(fetcher, origin)
            scan = await scan_sitemaps(fetcher, origin, robots.sitemaps, settings.max_urls_per_run)
            await asyncio.to_thread(
                repo.update_run, run_id, origin=origin, urls_found=len(scan.entries), truncated=scan.truncated
            )

            unique = list({e.loc: e for e in scan.entries}.values())
            done = 0

            async def one(entry):
                nonlocal done
                result = await check_url(fetcher, robots, entry)
                done += 1
                if done % 25 == 0:
                    await asyncio.to_thread(repo.update_run, run_id, urls_checked=done)
                return result

            results = await asyncio.gather(*(one(e) for e in unique))

        found = evaluate(origin, robots, scan, results)
        url_rows = [_url_row(r) for r in results]
        await asyncio.to_thread(repo.save_results, run_id, url_rows, found)

        key = report_key(run["user_id"], run_id)
        await asyncio.to_thread(store.put_text, key, build_csv(url_rows, found))

        await asyncio.to_thread(
            repo.update_run,
            run_id,
            status="done",
            finished_at=repo.now(),
            urls_checked=len(results),
            report_key=key,
            **severity_counts(found),
        )
    except Exception as e:  # the run must always end in a final state
        log.exception("crawl run %s failed", run_id)
        await asyncio.to_thread(
            repo.update_run, run_id, status="failed", finished_at=repo.now(), error_message=str(e)[:500]
        )
