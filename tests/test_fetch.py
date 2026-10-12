import pytest

from server.crawler.fetch import BlockedURL, SafeFetcher, check_url_shape, is_public_ip

from .conftest import public_resolver


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://intranet/",
        "http://example.com:8080/",
        "http://user:pass@example.com/",
        "http://printer.local/",
    ],
)
def test_blocked_shapes(url):
    with pytest.raises(BlockedURL):
        check_url_shape(url)


def test_allowed_shape():
    assert check_url_shape("https://Example.COM/path") == ("example.com", 443)


@pytest.mark.parametrize(
    "ip,public",
    [
        ("8.8.8.8", True),
        ("10.0.0.5", False),
        ("192.168.1.1", False),
        ("172.16.0.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::1", False),
        ("fd00::1", False),
        ("::ffff:10.0.0.1", False),
        ("2606:4700::1111", True),
    ],
)
def test_public_ip(ip, public):
    assert is_public_ip(ip) is public


@pytest.mark.anyio
async def test_redirect_chain_recorded(site):
    site.redirect("http://example.com/a", "https://example.com/a")
    site.redirect("https://example.com/a", "/b", status=302)
    site.html("https://example.com/b")
    async with SafeFetcher(delay_ms=0, transport=site.transport(), resolver=public_resolver) as f:
        r = await f.fetch("http://example.com/a")
    assert r.ok and r.final_url == "https://example.com/b"
    assert [(h.url, h.status) for h in r.chain] == [
        ("http://example.com/a", 301),
        ("https://example.com/a", 302),
    ]


@pytest.mark.anyio
async def test_too_many_redirects(site):
    for i in range(10):
        site.redirect(f"https://example.com/{i}", f"https://example.com/{i + 1}")
    async with SafeFetcher(delay_ms=0, transport=site.transport(), resolver=public_resolver) as f:
        r = await f.fetch("https://example.com/0", max_hops=5)
    assert r.error and "Too many redirects" in r.error


@pytest.mark.anyio
async def test_redirect_to_private_host_blocked(site):
    site.redirect("https://example.com/", "http://localhost/admin")
    async with SafeFetcher(delay_ms=0, transport=site.transport(), resolver=public_resolver) as f:
        r = await f.fetch("https://example.com/")
    assert r.error and r.error.startswith("Blocked")
    assert "http://localhost/admin" not in site.requests


@pytest.mark.anyio
async def test_dns_to_private_ip_blocked(site):
    async def private(host, port):
        return ["10.1.2.3"]

    site.html("https://example.com/")
    async with SafeFetcher(delay_ms=0, transport=site.transport(), resolver=private) as f:
        r = await f.fetch("https://example.com/")
    assert r.error and "non-public" in r.error
    assert site.requests == []


@pytest.mark.anyio
async def test_body_capped(site):
    site.add("https://example.com/big", "x" * 5000)
    async with SafeFetcher(delay_ms=0, transport=site.transport(), resolver=public_resolver) as f:
        r = await f.fetch("https://example.com/big", want_body=True, max_bytes=1000)
    assert len(r.body) == 1000 and r.body_truncated
