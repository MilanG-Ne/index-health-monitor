import pytest

from server.crawler.page import is_noindex_header, is_noindex_meta, normalize_url, parse_head


def test_parse_head():
    html = b"""<html><head>
    <meta name="ROBOTS" content="index, follow">
    <meta name="googlebot" content="noindex">
    <link rel="canonical" href="/page">
    </head><body><link rel="canonical" href="/ignored-not-in-head"></body></html>"""
    s = parse_head(html, "https://example.com/page?x=1")
    assert s.canonicals == ["https://example.com/page"]
    assert s.meta_robots == "index, follow; googlebot: noindex"
    assert is_noindex_meta(s.meta_robots)


@pytest.mark.parametrize(
    "meta,expected",
    [(None, False), ("index, follow", False), ("noindex", True), ("NONE", True), ("max-snippet:50", False)],
)
def test_noindex_meta(meta, expected):
    assert is_noindex_meta(meta) is expected


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], False),
        (["noindex"], True),
        (["googlebot: noindex"], True),
        (["otherbot: noindex"], False),
        (["unavailable_after: 25 Jun 2010 15:00:00 PST"], False),
        (["nofollow", "noindex, noarchive"], True),
    ],
)
def test_noindex_header(values, expected):
    assert is_noindex_header(values) is expected


def test_normalize_url():
    assert normalize_url("HTTPS://Example.com:443/a#top") == "https://example.com/a"
    assert normalize_url("http://example.com") == "http://example.com/"
    assert normalize_url("https://example.com/a/") != normalize_url("https://example.com/a")
