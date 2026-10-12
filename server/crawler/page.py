"""Indexing signals from a page: meta robots, X-Robots-Tag and canonical."""

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser


@dataclass
class PageSignals:
    meta_robots: str | None = None  # robots + googlebot meta values, joined
    canonicals: list[str] | None = None


def parse_head(html: bytes, base_url: str) -> PageSignals:
    tree = LexborHTMLParser(html.decode("utf-8", errors="replace"))
    head = tree.head or tree.root
    if head is None:
        return PageSignals(canonicals=[])
    robots_values = []
    for meta in head.css("meta[name]"):
        name = (meta.attributes.get("name") or "").strip().lower()
        if name in ("robots", "googlebot"):
            content = (meta.attributes.get("content") or "").strip()
            if content:
                robots_values.append(content if name == "robots" else f"googlebot: {content}")
    canonicals = []
    for link in head.css("link[rel]"):
        rel = (link.attributes.get("rel") or "").lower().split()
        href = (link.attributes.get("href") or "").strip()
        if "canonical" in rel and href:
            canonicals.append(urljoin(base_url, href))
    return PageSignals(meta_robots="; ".join(robots_values) or None, canonicals=canonicals)


def _directives(value: str) -> set[str]:
    return {d.strip().lower() for d in value.replace(";", ",").split(",") if d.strip()}


def is_noindex_meta(meta_robots: str | None) -> bool:
    if not meta_robots:
        return False
    for part in meta_robots.split(";"):
        part = part.strip()
        if part.lower().startswith("googlebot:"):
            part = part.split(":", 1)[1]
        if _directives(part) & {"noindex", "none"}:
            return True
    return False


def is_noindex_header(values: list[str]) -> bool:
    """X-Robots-Tag values may be global ("noindex") or scoped ("googlebot: noindex")."""
    for value in values:
        target, rules = None, value
        if ":" in value:
            maybe_agent, rest = value.split(":", 1)
            # "unavailable_after: date" is a rule, not a user agent.
            if maybe_agent.strip().lower() not in ("unavailable_after",) and " " not in maybe_agent.strip():
                target, rules = maybe_agent.strip().lower(), rest
        if target not in (None, "googlebot"):
            continue
        if _directives(rules) & {"noindex", "none"}:
            return True
    return False


def normalize_url(url: str) -> str:
    """Normalises for comparison: lowercase scheme/host, default ports and fragments removed."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port in (None, 80 if scheme == "http" else 443) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
