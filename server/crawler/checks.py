"""Turns crawl data into issues. Pure functions, no I/O."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .page import is_noindex_header, is_noindex_meta, normalize_url
from .robots import Robots
from .sitemaps import SitemapScan, parse_lastmod

ERROR, WARNING, INFO = "error", "warning", "info"

# code -> (severity, title, why it matters)
ISSUE_INFO: dict[str, tuple[str, str, str]] = {
    "URL_NOT_200": (
        ERROR,
        "Sitemap URL doesn't return 200",
        "Sitemaps should only list live pages. Broken URLs waste crawl budget and make Google trust the sitemap less.",
    ),
    "URL_REDIRECTS": (
        WARNING,
        "Sitemap URL redirects",
        "List the final URL instead. A sitemap full of redirects sends mixed signals about which URL is canonical.",
    ),
    "REDIRECT_CHAIN": (
        WARNING,
        "Redirect chain (more than one hop)",
        "Each extra hop slows crawling and can lose signals. Point the first URL straight at the final one.",
    ),
    "NOINDEX_IN_SITEMAP": (
        ERROR,
        "Noindex page listed in the sitemap",
        "The sitemap asks Google to index the page while the page says not to. Remove it from the sitemap or drop the noindex.",
    ),
    "BLOCKED_FOR_GOOGLEBOT": (
        ERROR,
        "Blocked by robots.txt for Googlebot",
        "Google can't crawl the page, so it can't see its content or a noindex. Blocked URLs can still appear in results without a description.",
    ),
    "CANONICAL_MISMATCH": (
        WARNING,
        "Canonical points to a different URL",
        "The sitemap and the page disagree about the preferred URL. List the canonical URL in the sitemap instead.",
    ),
    "CANONICAL_MULTIPLE": (
        WARNING,
        "More than one canonical tag",
        "When a page declares several canonicals, Google may ignore all of them.",
    ),
    "CANONICAL_MISSING": (
        INFO,
        "No canonical tag",
        "A self-referencing canonical helps Google pick the right URL when parameters or duplicates exist.",
    ),
    "PROTOCOL_HOST_MISMATCH": (
        WARNING,
        "Different protocol or host than the site",
        "http vs https or www vs non-www URLs in the sitemap usually point to duplicates or redirects.",
    ),
    "DUPLICATE_IN_SITEMAP": (
        INFO,
        "Listed more than once",
        "Duplicate entries are harmless but usually mean the sitemap generator is misconfigured.",
    ),
    "LASTMOD_FUTURE": (
        WARNING,
        "lastmod is in the future",
        "Impossible dates make Google distrust lastmod for the whole sitemap.",
    ),
    "LASTMOD_INVALID": (
        INFO,
        "lastmod isn't a valid date",
        "Use W3C format, for example 2026-10-11 or 2026-10-11T09:30:00+00:00.",
    ),
    "LASTMOD_UNIFORM": (
        WARNING,
        "Most URLs share the same lastmod",
        "This is usually a build timestamp. If every URL looks updated on every release, Google learns to ignore lastmod.",
    ),
    "LASTMOD_MISSING": (
        INFO,
        "No lastmod values",
        "Accurate lastmod dates help Google recrawl changed pages sooner. Leave them out rather than inventing them.",
    ),
    "NO_SITEMAP": (
        ERROR,
        "No sitemap found",
        "No sitemap was found in robots.txt, /sitemap.xml or /sitemap_index.xml. New pages are discovered more slowly without one.",
    ),
    "SITEMAP_ERROR": (
        ERROR,
        "Sitemap couldn't be read",
        "Google can't use a sitemap it can't fetch or parse.",
    ),
    "SITEMAP_TOO_LARGE": (
        ERROR,
        "Sitemap over the protocol limits",
        "A sitemap can hold at most 50,000 URLs and 50 MB uncompressed. Split it and use a sitemap index.",
    ),
    "ROBOTS_NO_SITEMAP_LINE": (
        INFO,
        "robots.txt doesn't list the sitemap",
        "A Sitemap: line in robots.txt lets every search engine find the sitemap without Search Console.",
    ),
    "ROBOTS_UNREACHABLE": (
        ERROR,
        "robots.txt returns a server error",
        "While robots.txt returns 5xx or times out, Google stops crawling the whole site.",
    ),
    "SKIPPED_BY_ROBOTS": (
        INFO,
        "Not checked (robots.txt blocks this tool)",
        "The site's robots.txt asks this crawler not to fetch the page, so it wasn't checked.",
    ),
    "RUN_TRUNCATED": (
        INFO,
        "Only part of the sitemap was checked",
        "The run stopped at the URL limit. Fix the issues found, then run again.",
    ),
}


@dataclass
class UrlResult:
    url: str
    sitemap: str
    lastmod: str | None
    status: int | None = None
    final_url: str | None = None
    chain: list[dict] = field(default_factory=list)
    meta_robots: str | None = None
    x_robots_tags: list[str] = field(default_factory=list)
    canonicals: list[str] = field(default_factory=list)
    is_html: bool = False
    blocked_for_googlebot: bool = False
    skipped: bool = False
    error: str | None = None
    fetch_ms: int = 0


def issue(code: str, url: str | None = None, detail: str | None = None) -> dict:
    return {"code": code, "severity": ISSUE_INFO[code][0], "url": url, "detail": detail}


def _origin(url: str) -> tuple[str, str]:
    p = urlsplit(url)
    return p.scheme.lower(), (p.hostname or "").lower()


def evaluate(
    origin: str,
    robots: Robots,
    scan: SitemapScan,
    results: list[UrlResult],
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out: list[dict] = []

    # Site level
    if robots.disallow_all:
        out.append(issue("ROBOTS_UNREACHABLE", detail=robots.error))
    elif not robots.sitemaps:
        missing = robots.status is not None and not 200 <= robots.status < 300
        out.append(issue("ROBOTS_NO_SITEMAP_LINE", detail=f"No robots.txt (HTTP {robots.status})" if missing else None))

    good_files = [f for f in scan.files if f.kind]
    if not good_files:
        tried = ", ".join(f"{f.url} ({f.error})" for f in scan.files) or "nothing to try"
        out.append(issue("NO_SITEMAP", detail=f"Tried: {tried}"))
    for f in scan.files:
        if f.error and f.kind is None and good_files:
            out.append(issue("SITEMAP_ERROR", url=f.url, detail=f.error))
        if f.too_large:
            out.append(issue("SITEMAP_TOO_LARGE", url=f.url, detail=f"{f.count} URLs"))
    if scan.truncated:
        out.append(issue("RUN_TRUNCATED", detail=f"Stopped after {len(scan.entries)} URLs"))

    # lastmod patterns
    parsed = [(e, parse_lastmod(e.lastmod)) for e in scan.entries]
    with_lastmod = [(e, d) for e, d in parsed if e.lastmod]
    if scan.entries and not with_lastmod:
        out.append(issue("LASTMOD_MISSING"))
    for e, d in with_lastmod:
        if d is None:
            out.append(issue("LASTMOD_INVALID", url=e.loc, detail=e.lastmod))
        elif d > now + timedelta(days=1):
            out.append(issue("LASTMOD_FUTURE", url=e.loc, detail=e.lastmod))
    dates = Counter(d.date() for _, d in with_lastmod if d is not None)
    if len(with_lastmod) >= 20 and dates:
        day, count = dates.most_common(1)[0]
        if count / len(with_lastmod) >= 0.8:
            out.append(
                issue(
                    "LASTMOD_UNIFORM",
                    detail=f"{count} of {len(with_lastmod)} URLs have lastmod {day.isoformat()}",
                )
            )

    # Duplicates and host/protocol
    site_scheme, site_host = _origin(origin)
    counts = Counter(normalize_url(e.loc) for e in scan.entries)
    for url, n in counts.items():
        if n > 1:
            out.append(issue("DUPLICATE_IN_SITEMAP", url=url, detail=f"Listed {n} times"))
    flagged_hosts = set()
    for e in scan.entries:
        scheme, host = _origin(e.loc)
        if (scheme, host) != (site_scheme, site_host) and e.loc not in flagged_hosts:
            flagged_hosts.add(e.loc)
            out.append(
                issue("PROTOCOL_HOST_MISMATCH", url=e.loc, detail=f"Site is {site_scheme}://{site_host}")
            )

    # Per URL
    for r in results:
        if r.blocked_for_googlebot and not robots.disallow_all:
            out.append(issue("BLOCKED_FOR_GOOGLEBOT", url=r.url))
        if r.skipped:
            out.append(issue("SKIPPED_BY_ROBOTS", url=r.url))
            continue
        if r.error:
            out.append(issue("URL_NOT_200", url=r.url, detail=r.error))
            continue
        if r.chain:
            hops = " → ".join(f"{h['status']} {h['url']}" for h in r.chain)
            out.append(issue("URL_REDIRECTS", url=r.url, detail=f"{hops} → {r.status} {r.final_url}"))
            if len(r.chain) > 1:
                out.append(issue("REDIRECT_CHAIN", url=r.url, detail=f"{len(r.chain)} hops"))
        if r.status is None or not 200 <= r.status < 300:
            out.append(issue("URL_NOT_200", url=r.url, detail=f"HTTP {r.status}"))
            continue
        if is_noindex_meta(r.meta_robots):
            out.append(issue("NOINDEX_IN_SITEMAP", url=r.url, detail=f"meta robots: {r.meta_robots}"))
        elif is_noindex_header(r.x_robots_tags):
            out.append(
                issue("NOINDEX_IN_SITEMAP", url=r.url, detail=f"X-Robots-Tag: {', '.join(r.x_robots_tags)}")
            )
        if r.is_html:
            if len(r.canonicals) > 1:
                out.append(issue("CANONICAL_MULTIPLE", url=r.url, detail=" | ".join(r.canonicals)))
            elif not r.canonicals:
                out.append(issue("CANONICAL_MISSING", url=r.url))
            elif normalize_url(r.canonicals[0]) != normalize_url(r.final_url or r.url):
                out.append(issue("CANONICAL_MISMATCH", url=r.url, detail=f"canonical: {r.canonicals[0]}"))
    return out


def severity_counts(issues: list[dict]) -> dict[str, int]:
    c = Counter(i["severity"] for i in issues)
    return {"errors": c[ERROR], "warnings": c[WARNING], "notices": c[INFO]}
