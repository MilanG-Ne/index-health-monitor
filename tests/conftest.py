import gzip
import os
import tempfile

import httpx
import pytest

_tmp = tempfile.mkdtemp(prefix="ihm-tests-")
os.environ["AUTH_MODE"] = "dev"
os.environ["STORAGE_MODE"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = os.path.join(_tmp, "storage")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["CRAWL_DELAY_MS"] = "0"
os.environ.pop("REPL_ID", None)


async def public_resolver(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


class FakeSite:
    """An in-memory website for httpx.MockTransport."""

    def __init__(self):
        self.pages: dict[str, tuple[int, dict, bytes]] = {}
        self.requests: list[str] = []

    def add(self, url: str, body: str | bytes = "", status: int = 200, headers: dict | None = None):
        if isinstance(body, str):
            body = body.encode()
        self.pages[url] = (status, headers or {}, body)
        return self

    def html(self, url: str, head: str = "", status: int = 200, headers: dict | None = None):
        return self.add(
            url,
            f"<!doctype html><html><head>{head}</head><body>ok</body></html>",
            status,
            {"content-type": "text/html; charset=utf-8", **(headers or {})},
        )

    def redirect(self, url: str, to: str, status: int = 301):
        return self.add(url, "", status, {"location": to})

    def xml(self, url: str, body: str, gz: bool = False):
        data = gzip.compress(body.encode()) if gz else body.encode()
        return self.add(url, data, 200, {"content-type": "application/xml"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url not in self.pages:
            return httpx.Response(404, text="not found")
        status, headers, body = self.pages[url]
        return httpx.Response(status, headers=headers, content=body)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def site() -> FakeSite:
    return FakeSite()


def urlset(*urls: tuple[str, str | None]) -> str:
    items = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>" for u, m in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'


def sitemapindex(*locs: str) -> str:
    items = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</sitemapindex>'
