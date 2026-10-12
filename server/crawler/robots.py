"""robots.txt parsing with Google's matching rules.

Python's urllib.robotparser only does prefix matching, but Google supports
`*` and `$` and picks the most specific (longest) matching rule, with Allow
winning ties. This module implements that behaviour.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .fetch import ROBOTS_TOKEN, SafeFetcher


@dataclass
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern

    @classmethod
    def make(cls, allow: bool, pattern: str) -> "Rule":
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        return cls(allow, pattern, re.compile(regex + ("$" if anchored else "")))


@dataclass
class Robots:
    groups: dict[str, list[Rule]] = field(default_factory=dict)  # user agent token -> rules
    sitemaps: list[str] = field(default_factory=list)
    status: int | None = None
    error: str | None = None
    # Google treats a 5xx or unreachable robots.txt as "disallow everything" for Googlebot.
    # The crawler itself still checks pages, so the report can show what is behind it.
    disallow_all: bool = False

    def rules_for(self, token: str) -> list[Rule]:
        token = token.lower()
        if token in self.groups:
            return self.groups[token]
        return self.groups.get("*", [])

    def allowed(self, url: str, token: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        best: Rule | None = None
        for rule in self.rules_for(token):
            if not rule.pattern:
                continue
            if rule.regex.match(path):
                if (
                    best is None
                    or len(rule.pattern) > len(best.pattern)
                    or (len(rule.pattern) == len(best.pattern) and rule.allow and not best.allow)
                ):
                    best = rule
        return best is None or best.allow

    def allowed_for_googlebot(self, url: str) -> bool:
        return not self.disallow_all and self.allowed(url, "googlebot")

    def allowed_for_us(self, url: str) -> bool:
        return self.allowed(url, ROBOTS_TOKEN)


def parse_robots(text: str) -> Robots:
    robots = Robots()
    current_agents: list[str] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                current_agents, in_rules = [], False
            agent = value.lower()
            current_agents.append(agent)
            robots.groups.setdefault(agent, [])
        elif key in ("allow", "disallow"):
            in_rules = True
            for agent in current_agents:
                robots.groups[agent].append(Rule.make(key == "allow", value))
        elif key == "sitemap":
            if value:
                robots.sitemaps.append(value)
    return robots


async def load_robots(fetcher: SafeFetcher, origin: str) -> Robots:
    url = origin.rstrip("/") + "/robots.txt"
    res = await fetcher.fetch(url, want_body=True, max_bytes=512 * 1024)
    if res.error:
        return Robots(error=res.error, disallow_all=True)
    if res.status and 200 <= res.status < 300:
        robots = parse_robots((res.body or b"").decode("utf-8", errors="replace"))
        robots.status = res.status
        return robots
    if res.status and res.status >= 500:
        return Robots(status=res.status, disallow_all=True, error=f"robots.txt returned {res.status}")
    # 4xx: Google treats this as "no restrictions".
    return Robots(status=res.status)
