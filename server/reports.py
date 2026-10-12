"""CSV report for one crawl run."""

import csv
import io
from collections import defaultdict


COLUMNS = [
    "url",
    "issues",
    "status_code",
    "final_url",
    "redirect_hops",
    "redirect_chain",
    "meta_robots",
    "x_robots_tag",
    "canonical",
    "blocked_for_googlebot",
    "lastmod",
    "sitemap",
    "fetch_ms",
    "error",
]


def build_csv(url_rows: list[dict], issue_rows: list[dict]) -> str:
    by_url: dict[str | None, list[str]] = defaultdict(list)
    for i in issue_rows:
        by_url[i["url"]].append(i["code"])

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    for code in by_url.get(None, []):
        w.writerow({"url": "(site)", "issues": code})
    listed = set()
    for r in url_rows:
        listed.add(r["url"])
        chain = r.get("redirect_chain") or []
        w.writerow(
            {
                **r,
                "issues": " ".join(by_url.get(r["url"], [])),
                "redirect_hops": len(chain),
                "redirect_chain": " -> ".join(f"{h['status']} {h['url']}" for h in chain),
            }
        )
    # Issues on URLs that weren't fetched (e.g. sitemap files, duplicates normalised differently).
    for url, codes in by_url.items():
        if url is not None and url not in listed:
            w.writerow({"url": url, "issues": " ".join(codes)})
    return buf.getvalue()
