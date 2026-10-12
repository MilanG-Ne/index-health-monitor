"""Safe HTTP fetching for user-supplied URLs.

- Only http/https on ports 80 and 443.
- Every host (including each redirect hop) must resolve to public IP addresses only.
- Redirects are followed manually so the full chain can be reported.
- Response bodies are capped and only read when the caller asks for them.
"""

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

USER_AGENT = "IndexHealthMonitor/1.0 (+https://index.ivig.dev/bot)"
ROBOTS_TOKEN = "indexhealthmonitor"

Resolver = Callable[[str, int], Awaitable[list[str]]]


class BlockedURL(Exception):
    """The URL points somewhere the crawler must not go."""


@dataclass
class Hop:
    url: str
    status: int


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None = None
    chain: list[Hop] = field(default_factory=list)  # redirect hops before the final response
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    body: bytes | None = None
    body_truncated: bool = False
    elapsed_ms: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list({info[4][0] for info in infos})


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"))
    )


def check_url_shape(url: str) -> tuple[str, int]:
    """Validates scheme, host and port without touching the network. Returns (host, port)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("Only http and https URLs are allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedURL("URL has no host")
    if parts.username or parts.password:
        raise BlockedURL("URLs with credentials are not allowed")
    try:
        ipaddress.ip_address(host)
        raise BlockedURL("Use a domain name, not an IP address")
    except ValueError:
        pass
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
        raise BlockedURL("That host is not a public website")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise BlockedURL("Invalid port")
    if port not in (80, 443):
        raise BlockedURL("Only ports 80 and 443 are allowed")
    return host, port


async def assert_public_url(url: str, resolver: Resolver = default_resolver) -> None:
    host, port = check_url_shape(url)
    try:
        ips = await resolver(host, port)
    except (socket.gaierror, OSError):
        raise BlockedURL(f"Could not resolve {host}")
    if not ips:
        raise BlockedURL(f"Could not resolve {host}")
    for ip in ips:
        if not is_public_ip(ip):
            raise BlockedURL(f"{host} resolves to a non-public address")


class SafeFetcher:
    def __init__(
        self,
        concurrency: int = 4,
        delay_ms: int = 250,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = default_resolver,
    ):
        self._sem = asyncio.Semaphore(concurrency)
        self._delay = delay_ms / 1000
        self._resolver = resolver
        self._host_ok: dict[str, bool] = {}
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_s),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def _check(self, url: str) -> None:
        host, _ = check_url_shape(url)
        cached = self._host_ok.get(host)
        if cached is True:
            return
        await assert_public_url(url, self._resolver)
        self._host_ok[host] = True

    async def fetch(
        self,
        url: str,
        *,
        want_body: Callable[[httpx.Response], bool] | bool = False,
        max_bytes: int = 2 * 1024 * 1024,
        max_hops: int = 5,
    ) -> FetchResult:
        result = FetchResult(url=url, final_url=url)
        started = time.monotonic()
        current = url
        try:
            async with self._sem:
                for _ in range(max_hops + 1):
                    await self._check(current)
                    async with self._client.stream("GET", current) as resp:
                        location = resp.headers.get("location")
                        if resp.status_code in (301, 302, 303, 307, 308) and location:
                            result.chain.append(Hop(current, resp.status_code))
                            current = urljoin(current, location)
                            continue
                        result.final_url = current
                        result.status = resp.status_code
                        result.headers = resp.headers
                        read = want_body(resp) if callable(want_body) else want_body
                        if read:
                            chunks, size = [], 0
                            async for chunk in resp.aiter_bytes():
                                size += len(chunk)
                                if size > max_bytes:
                                    chunks.append(chunk[: max(0, len(chunk) - (size - max_bytes))])
                                    result.body_truncated = True
                                    break
                                chunks.append(chunk)
                            result.body = b"".join(chunks)
                        break
                else:
                    result.final_url = current
                    result.error = f"Too many redirects (more than {max_hops})"
                if self._delay:
                    await asyncio.sleep(self._delay)
        except BlockedURL as e:
            result.error = f"Blocked: {e}"
        except httpx.TimeoutException:
            result.error = "Timed out"
        except httpx.HTTPError as e:
            result.error = f"Request failed: {type(e).__name__}"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result
