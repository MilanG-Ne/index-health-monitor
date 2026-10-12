"""XML sitemap discovery and parsing (sitemap indexes, gzip, protocol limits)."""

import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin

from defusedxml import ElementTree as SafeET

from .fetch import SafeFetcher

MAX_URLS_PER_SITEMAP = 50_000  # sitemap protocol limit
MAX_SITEMAP_BYTES = 50 * 1024 * 1024  # 50 MB uncompressed, sitemap protocol limit
MAX_SITEMAPS = 50  # sitemap files read per run


@dataclass
class SitemapEntry:
    loc: str
    lastmod: str | None
    sitemap: str


@dataclass
class SitemapFile:
    url: str
    status: int | None
    kind: str | None = None  # "urlset" | "sitemapindex"
    count: int = 0
    error: str | None = None
    too_large: bool = False


@dataclass
class SitemapScan:
    entries: list[SitemapEntry] = field(default_factory=list)
    files: list[SitemapFile] = field(default_factory=list)
    truncated: bool = False
    from_robots: bool = False


def parse_lastmod(value: str | None) -> datetime | None:
    """Parses W3C datetime values (YYYY, YYYY-MM, YYYY-MM-DD, or a full timestamp)."""
    if not value:
        return None
    v = value.strip()
    try:
        if len(v) == 4:
            dt = datetime(int(v), 1, 1)
        elif len(v) == 7:
            dt = datetime(int(v[:4]), int(v[5:7]), 1)
        else:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decompress(data: bytes) -> tuple[bytes, bool]:
    """Gunzips with an output cap so a small file can't expand into gigabytes."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(data, MAX_SITEMAP_BYTES + 1)
    return out[:MAX_SITEMAP_BYTES], len(out) > MAX_SITEMAP_BYTES


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap_xml(data: bytes, sitemap_url: str) -> tuple[str, list[tuple[str, str | None]]]:
    """Returns (kind, [(loc, lastmod), ...]). Raises ValueError on invalid XML."""
    try:
        root = SafeET.fromstring(data)
    except SafeET.ParseError as e:
        raise ValueError(f"Invalid XML: {e}") from e
    except Exception as e:  # defusedxml raises its own errors for entity tricks
        raise ValueError(f"Rejected XML: {type(e).__name__}") from e
    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise ValueError(f"Not a sitemap (root element <{kind}>)")
    child_tag = "url" if kind == "urlset" else "sitemap"
    items = []
    for child in root:
        if _local(child.tag) != child_tag:
            continue
        loc = lastmod = None
        for el in child:
            name = _local(el.tag)
            if name == "loc" and el.text:
                loc = el.text.strip()
            elif name == "lastmod" and el.text:
                lastmod = el.text.strip()
        if loc:
            items.append((urljoin(sitemap_url, loc), lastmod))
    return kind, items


async def scan_sitemaps(
    fetcher: SafeFetcher,
    origin: str,
    robots_sitemaps: list[str],
    max_urls: int,
    max_depth: int = 2,
) -> SitemapScan:
    scan = SitemapScan(from_robots=bool(robots_sitemaps))
    origin = origin.rstrip("/")
    candidates = list(dict.fromkeys(robots_sitemaps)) or [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"]
    seen: set[str] = set()

    async def read(url: str, depth: int) -> None:
        if url in seen or len(seen) >= MAX_SITEMAPS or scan.truncated:
            return
        seen.add(url)
        res = await fetcher.fetch(url, want_body=True, max_bytes=MAX_SITEMAP_BYTES + 1)
        file = SitemapFile(url=url, status=res.status)
        scan.files.append(file)
        if res.error:
            file.error = res.error
            return
        if not res.ok:
            file.error = f"HTTP {res.status}"
            return
        data = res.body or b""
        if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
            try:
                data, over = _decompress(data)
            except zlib.error:
                file.error = "Could not decompress .gz sitemap"
                return
            file.too_large = file.too_large or over
        if len(data) > MAX_SITEMAP_BYTES or res.body_truncated:
            file.too_large = True
        try:
            kind, items = parse_sitemap_xml(data, res.final_url)
        except ValueError as e:
            file.error = str(e)
            return
        file.kind, file.count = kind, len(items)
        if len(items) > MAX_URLS_PER_SITEMAP:
            file.too_large = True
        if kind == "sitemapindex":
            if depth >= max_depth:
                file.error = "Nested sitemap index too deep; children skipped"
                return
            for loc, _ in items:
                await read(loc, depth + 1)
            return
        for loc, lastmod in items:
            if len(scan.entries) >= max_urls:
                scan.truncated = True
                return
            scan.entries.append(SitemapEntry(loc=loc, lastmod=lastmod, sitemap=url))

    for candidate in candidates:
        await read(candidate, 0)
        # Without robots.txt hints, stop at the first conventional location that works.
        if not scan.from_robots and any(f.kind for f in scan.files):
            break
    return scan
