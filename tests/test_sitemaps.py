import pytest

from server.crawler.fetch import SafeFetcher
from server.crawler.sitemaps import parse_lastmod, scan_sitemaps

from .conftest import public_resolver, sitemapindex, urlset

O = "https://example.com"


async def scan(site, robots_sitemaps=(), max_urls=500):
    async with SafeFetcher(delay_ms=0, transport=site.transport(), resolver=public_resolver) as f:
        return await scan_sitemaps(f, O, list(robots_sitemaps), max_urls)


@pytest.mark.anyio
async def test_fallback_location(site):
    site.xml(f"{O}/sitemap.xml", urlset((f"{O}/", "2026-10-01"), (f"{O}/about", None)))
    s = await scan(site)
    assert [e.loc for e in s.entries] == [f"{O}/", f"{O}/about"]
    assert s.entries[0].lastmod == "2026-10-01"
    assert not s.from_robots


@pytest.mark.anyio
async def test_index_and_gzip(site):
    site.xml(f"{O}/sitemap_index.xml", sitemapindex(f"{O}/pages.xml.gz", f"{O}/posts.xml"))
    site.xml(f"{O}/pages.xml.gz", urlset((f"{O}/a", None)), gz=True)
    site.xml(f"{O}/posts.xml", urlset((f"{O}/b", None), (f"{O}/c", None)))
    s = await scan(site, [f"{O}/sitemap_index.xml"])
    assert {e.loc for e in s.entries} == {f"{O}/a", f"{O}/b", f"{O}/c"}
    assert {f.kind for f in s.files} == {"sitemapindex", "urlset"}


@pytest.mark.anyio
async def test_truncation(site):
    site.xml(f"{O}/sitemap.xml", urlset(*[(f"{O}/p{i}", None) for i in range(30)]))
    s = await scan(site, max_urls=10)
    assert len(s.entries) == 10 and s.truncated


@pytest.mark.anyio
async def test_invalid_xml_and_missing(site):
    site.add(f"{O}/bad.xml", "<urlset><url><loc>oops", headers={"content-type": "application/xml"})
    s = await scan(site, [f"{O}/bad.xml", f"{O}/missing.xml"])
    assert s.entries == []
    errors = {f.url: f.error for f in s.files}
    assert "Invalid XML" in errors[f"{O}/bad.xml"]
    assert errors[f"{O}/missing.xml"] == "HTTP 404"


@pytest.mark.anyio
async def test_entity_expansion_rejected(site):
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
        '<urlset><url><loc>&lol2;</loc></url></urlset>'
    )
    site.add(f"{O}/sitemap.xml", bomb)
    s = await scan(site)
    assert s.entries == [] and "Rejected XML" in s.files[0].error


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026", "2026-01-01"),
        ("2026-10", "2026-10-01"),
        ("2026-10-11", "2026-10-11"),
        ("2026-10-11T09:30:00Z", "2026-10-11"),
        ("2026-10-11T23:30:00-05:00", "2026-10-12"),
        ("yesterday", None),
    ],
)
def test_parse_lastmod(value, expected):
    d = parse_lastmod(value)
    assert (d.date().isoformat() if d else None) == expected
