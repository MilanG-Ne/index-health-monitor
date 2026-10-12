from server.crawler.robots import parse_robots

ROBOTS = """
# comment
User-agent: *
Disallow: /admin
Disallow: /*.pdf$
Allow: /admin/public
Disallow: /search?

User-agent: Googlebot
User-agent: Bingbot
Disallow: /private
Allow: /private/ok

Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/news.xml
"""


def test_sitemaps_collected():
    r = parse_robots(ROBOTS)
    assert r.sitemaps == ["https://example.com/sitemap.xml", "https://example.com/news.xml"]


def test_default_group_rules():
    r = parse_robots(ROBOTS)
    ua = "indexhealthmonitor"
    assert not r.allowed("https://example.com/admin/users", ua)
    assert r.allowed("https://example.com/admin/public/page", ua)  # longer Allow wins
    assert not r.allowed("https://example.com/files/report.pdf", ua)
    assert r.allowed("https://example.com/files/report.pdf?x=1", ua)  # $ anchors the end
    assert not r.allowed("https://example.com/search?q=shoes", ua)
    assert r.allowed("https://example.com/search", ua)
    assert r.allowed("https://example.com/", ua)


def test_specific_group_replaces_default():
    r = parse_robots(ROBOTS)
    # Googlebot has its own group, so the * rules don't apply to it.
    assert r.allowed_for_googlebot("https://example.com/admin/users")
    assert not r.allowed_for_googlebot("https://example.com/private/x")
    assert r.allowed_for_googlebot("https://example.com/private/ok/x")


def test_allow_wins_tie():
    r = parse_robots("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert r.allowed("https://example.com/page", "x")


def test_empty_disallow_allows_everything():
    r = parse_robots("User-agent: *\nDisallow:\n")
    assert r.allowed("https://example.com/anything", "x")


def test_disallow_all_only_affects_googlebot_view():
    r = parse_robots("")
    r.disallow_all = True
    assert not r.allowed_for_googlebot("https://example.com/")
    assert r.allowed_for_us("https://example.com/")
