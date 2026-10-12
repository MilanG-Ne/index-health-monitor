"""Full flow through the API against a fake website with known problems."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from server import main as main_module
from server.crawler.fetch import SafeFetcher

from .conftest import FakeSite, public_resolver, urlset

O = "https://shop.example.com"


def broken_site() -> FakeSite:
    s = FakeSite()
    s.redirect("http://shop.example.com/", f"{O}/")
    s.redirect("http://shop.example.com/p3", f"{O}/p3")
    s.html(f"{O}/", '<link rel="canonical" href="https://shop.example.com/">')
    s.add(
        f"{O}/robots.txt",
        "User-agent: *\nDisallow: /cart\nUser-agent: IndexHealthMonitor\nDisallow: /secret\n"
        f"Sitemap: {O}/sitemap.xml\n",
    )
    same_day = "2026-10-01T10:00:00+00:00"
    pages = [f"{O}/p{i}" for i in range(20)]
    for p in pages:
        s.html(p, f'<link rel="canonical" href="{p}">')
    s.html(f"{O}/hidden", '<meta name="robots" content="noindex"><link rel="canonical" href="https://shop.example.com/hidden">')
    s.html(f"{O}/header-hidden", '<link rel="canonical" href="https://shop.example.com/header-hidden">', headers={"x-robots-tag": "noindex"})
    s.redirect(f"{O}/old", f"{O}/p1")
    s.html(f"{O}/dupe", '<link rel="canonical" href="https://shop.example.com/p1">')
    s.add(f"{O}/gone", "gone", status=410)
    s.html(f"{O}/cart")
    s.html(f"{O}/secret")
    s.xml(
        f"{O}/sitemap.xml",
        urlset(
            *[(p, same_day) for p in pages],
            (f"{O}/hidden", same_day),
            (f"{O}/header-hidden", same_day),
            (f"{O}/old", same_day),
            (f"{O}/dupe", same_day),
            (f"{O}/gone", same_day),
            (f"{O}/cart", same_day),
            (f"{O}/secret", same_day),
            (f"{O}/p0", same_day),
            ("http://shop.example.com/p3", same_day),
            (f"{O}/p2", "2099-01-01"),
        ),
    )
    return s


@pytest.fixture
def client(monkeypatch):
    fake = broken_site()

    async def fake_assert_public(url, resolver=None):
        return None

    monkeypatch.setattr(main_module, "assert_public_url", fake_assert_public)
    app = main_module.create_app()
    app.state.fetcher_factory = lambda s: SafeFetcher(delay_ms=0, transport=fake.transport(), resolver=public_resolver)
    with TestClient(app) as c:
        yield c


def test_requires_login(client):
    assert client.get("/api/sites").status_code == 401


def test_rejects_private_targets(client, monkeypatch):
    client.get("/auth/login")
    r = client.post("/api/sites", json={"root_url": "http://localhost:8000"})
    assert r.status_code == 400


def test_full_run(client):
    assert client.get("/auth/login", follow_redirects=False).status_code == 303
    me = client.get("/api/me").json()
    assert me["id"] == "dev-user"

    site = client.post("/api/sites", json={"root_url": "http://shop.example.com/some/page"}).json()
    assert site["root_url"] == "http://shop.example.com"

    run_id = client.post(f"/api/sites/{site['id']}/runs").json()["id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "done", run
    assert run["origin"] == O  # followed the http -> https redirect
    assert run["urls_found"] == 30

    groups = {g["code"]: g for g in client.get(f"/api/runs/{run_id}/issues").json()}
    urls = lambda code: {i["url"] for i in groups[code]["items"]}  # noqa: E731

    assert urls("URL_NOT_200") == {f"{O}/gone"}
    assert urls("URL_REDIRECTS") == {f"{O}/old", "http://shop.example.com/p3"}
    assert urls("NOINDEX_IN_SITEMAP") == {f"{O}/hidden", f"{O}/header-hidden"}
    assert urls("BLOCKED_FOR_GOOGLEBOT") == {f"{O}/cart"}
    assert urls("SKIPPED_BY_ROBOTS") == {f"{O}/secret"}
    assert urls("CANONICAL_MISMATCH") == {f"{O}/dupe"}
    assert urls("DUPLICATE_IN_SITEMAP") == {f"{O}/p0", f"{O}/p2"}
    assert urls("PROTOCOL_HOST_MISMATCH") == {"http://shop.example.com/p3"}
    assert urls("LASTMOD_FUTURE") == {f"{O}/p2"}
    assert "LASTMOD_UNIFORM" in groups
    assert "ROBOTS_NO_SITEMAP_LINE" not in groups
    assert groups["URL_NOT_200"]["why"]

    assert run["errors"] == sum(g["count"] for g in groups.values() if g["severity"] == "error")

    page = client.get(f"/api/runs/{run_id}/urls?per_page=10").json()
    assert page["total"] == 28 and len(page["items"]) == 10  # duplicates fetched once

    r = client.get(f"/api/runs/{run_id}/report.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    gone = next(row for row in rows if row["url"] == f"{O}/gone")
    assert gone["status_code"] == "410" and "URL_NOT_200" in gone["issues"]

    # Another user can't see this run.
    client.post("/auth/logout")
    assert client.get(f"/api/runs/{run_id}").status_code == 401


def test_one_active_run_and_delete(client):
    client.get("/auth/login")
    site = client.post("/api/sites", json={"root_url": "shop.example.com"}).json()
    assert client.patch(f"/api/sites/{site['id']}", json={"weekly_check": False}).json()["weekly_check"] is False
    assert client.delete(f"/api/sites/{site['id']}").status_code == 204
    assert client.get(f"/api/sites/{site['id']}").status_code == 404
