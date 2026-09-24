import json


from yabiztracker.services.social_finder import (
    SocialFinderConfig,
    SocialLinkFinder,
    canonical_social_url,
    extract_social_links,
    merge_social_links,
    platform_for_url,
    social_text,
)
from yabiztracker.database import Database


def test_social_platforms_and_urls_are_normalized():
    html = r'''
      <a href="https://vk.com/example?utm_source=x">VK</a>
      https:\/\/t.me/example
      https://max.ru/channel?id=42&utm_medium=x
      https://ok.ru/group
      https://dzen.ru/example
      https://rutube.ru/channel/123/
      https://www.youtube.com/@example
      https://viber.click/123456789
      https://wa.me/79990000000
    '''
    links = extract_social_links(html)
    assert "https://vk.com/example" in links["vk"]
    assert "https://t.me/example" in links["telegram"]
    assert "https://max.ru/channel?id=42" in links["max"]
    assert "https://ok.ru/group" in links["ok"]
    assert "https://dzen.ru/example" in links["dzen"]
    assert "https://rutube.ru/channel/123" in links["rutube"]
    assert "https://www.youtube.com/@example" in links["youtube"]
    assert "https://viber.click/123456789" in links["viber"]
    assert "https://wa.me/79990000000" in links["whatsapp"]


def test_legacy_social_json_and_multiple_links_are_merged():
    old = {"vk": "https://vk.com/old"}
    new = {"vk": ["https://vk.com/new", "https://vk.com/old"], "max": ["https://max.ru/channel"]}
    merged = merge_social_links(old, new)
    assert merged == {
        "vk": ["https://vk.com/old", "https://vk.com/new"],
        "max": ["https://max.ru/channel"],
    }
    assert "https://vk.com/old" in social_text(merged)


def test_supported_platform_detection():
    assert platform_for_url("https://vk.ru/club") == "vk"
    assert platform_for_url("https://max.ru/channel") == "max"
    assert platform_for_url("https://t.me/channel") == "telegram"
    assert platform_for_url("https://example.org/social") is None
    assert canonical_social_url("vk.com/test?utm_campaign=x") == "https://vk.com/test"


def test_yandex_maps_url_contains_stable_org_id():
    url = SocialLinkFinder.yandex_maps_url("Море Котиков", "137591097049")
    assert url.endswith("/137591097049/")
    assert "more_kotikov" in url


def test_social_finder_extracts_and_validates_yandex_and_site_links():
    class FakeFinder(SocialLinkFinder):
        def __init__(self):
            super().__init__(None, SocialFinderConfig(validate_links=True))
            self.calls = []

        def _fetch(self, url):
            self.calls.append(url)
            if "yandex.ru/maps" in url:
                return '<a href="https://max.ru/more_cats">MAX</a><a href="https://vk.com/more_cats">VK</a>', url
            return '<a href="https://t.me/more_cats">Telegram</a>', url

        def _validate(self, url):
            return "vk.com" in url or "max.ru" in url or "t.me" in url

    finder = FakeFinder()
    result = finder.scan({"id": "137591097049", "name": "Море Котиков", "website": "https://morecats.example"})
    assert result.status == "found"
    assert result.links["max"] == ["https://max.ru/more_cats"]
    assert result.links["vk"] == ["https://vk.com/more_cats"]
    assert result.links["telegram"] == ["https://t.me/more_cats"]
    assert len(finder.calls) == 2


def test_database_social_migration_and_update_are_backward_compatible(tmp_path):
    db = Database(str(tmp_path / "organizations.db"))
    with db._lock:
        db.conn.execute(
            "INSERT INTO organizations(org_id,name,first_seen_date,social_links) VALUES(?,?,?,?)",
            ("1", "Test", "2026-09-01T00:00:00", json.dumps({"vk": "https://vk.com/old"}, ensure_ascii=False)),
        )
        db.conn.commit()
    assert db.update_organization_socials("1", {"vk": ["https://vk.com/new"], "max": ["https://max.ru/channel"]}, "found")
    row = db.get_by_id("1")
    data = json.loads(row["social_links"])
    assert data["vk"] == ["https://vk.com/old", "https://vk.com/new"]
    assert data["max"] == ["https://max.ru/channel"]
    assert row["social_scan_status"] == "found"
    assert db.get_social_scan_candidates(force=True)[0]["id"] == "1"


def test_existing_schema_v9_is_migrated_to_v10(tmp_path):
    import sqlite3
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE organizations (org_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT, category TEXT, subcategory TEXT, phone TEXT, website TEXT, email TEXT, social_links TEXT, latitude REAL, longitude REAL, first_seen_date TEXT NOT NULL, last_updated TEXT, city_name TEXT DEFAULT '', status TEXT DEFAULT 'Новый', comment TEXT DEFAULT '', responsible TEXT DEFAULT '', next_contact_date TEXT DEFAULT '', last_seen_at TEXT DEFAULT '', missing_scan_count INTEGER DEFAULT 0, source_status TEXT DEFAULT 'unknown', categories_json TEXT DEFAULT '[]', email_scan_status TEXT DEFAULT 'not_scanned', email_scanned_at TEXT DEFAULT '', email_scan_error TEXT DEFAULT '', email_scan_pages INTEGER DEFAULT 0)")
    conn.execute("PRAGMA user_version=9")
    conn.commit(); conn.close()
    db = Database(str(path))
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 10
    cols = {row[1] for row in db.conn.execute("PRAGMA table_info(organizations)")}
    assert {"social_scan_status", "social_scanned_at", "social_scan_error"} <= cols


def test_social_extractor_rejects_yandex_maps_and_vk_assets_or_navigation_links():
    raw = """
    https://zen.yandex.ru/yandexmaps
    https://vk.com/yandex.maps
    https://login.vk.ru/
    https://login.vk.ru/?act=logout&hash=abc&_origin=https://vk.ru
    https://vk.com/wall-19542789_200541|руководством
    https://vk.com/faq21697|Как
    https://vk.ru/sticker/1-%id%-%size%
    https://st.vk.ru/css/al/common.css
    https://st.vk.ru/dist/web/chunks/common.js
    https://papi.vk.ru/pushsse/ruim
    https://vk.ru/
    https://vk.ru/usefull.php
    https://vk.ru/special.php
    https://vk.ru/jumpingmania
    https://vk.ru/club215292987
    https://vk.ru/fithall63
    https://vk.ru/dont_panic_42
    https://vk.ru/bearandbunny163
    https://max.ru/example_channel
    """
    links = extract_social_links(raw)
    assert links["vk"] == [
        "https://vk.ru/jumpingmania",
        "https://vk.ru/club215292987",
        "https://vk.ru/fithall63",
        "https://vk.ru/dont_panic_42",
        "https://vk.ru/bearandbunny163",
    ]
    assert links["max"] == ["https://max.ru/example_channel"]
    assert "dzen" not in links or "https://zen.yandex.ru/yandexmaps" not in links["dzen"]


def test_vk_platform_does_not_accept_subdomains():
    assert platform_for_url("https://st.vk.ru/css/base.css") is None
    assert platform_for_url("https://login.vk.ru/") is None
    assert platform_for_url("https://papi.vk.ru/pushsse/ruim") is None


def test_social_extractor_rejects_platform_service_and_yandex_links():
    raw = """
    https://dzen.yandex.ru/yandexmaps
    https://dzen.ru/yandexmaps
    https://dzen.ru/ddx_fitness
    https://t.me/mapsyandex
    https://t.me/yandexmaps
    https://t.me/ddx_fitness
    https://vk.com/yandex.maps
    https://vk.com/rtrg?p=VK-RTRG-1583133-ddikg
    https://vk.com/away.php?to=https://ya.cc/t/11VRxL_h3D3A7R&cc_key=
    https://vk.com/ddx_fitness
    https://ok.ru/friends
    https://ok.ru/ddx_fitness
    """
    links = extract_social_links(raw)

    assert links["dzen"] == ["https://dzen.ru/ddx_fitness"]
    assert links["telegram"] == ["https://t.me/ddx_fitness"]
    assert links["vk"] == ["https://vk.com/ddx_fitness"]
    assert links["ok"] == ["https://ok.ru/ddx_fitness"]


def test_canonical_social_url_rejects_service_urls_but_keeps_real_profiles():
    invalid = [
        "https://dzen.yandex.ru/yandexmaps",
        "https://dzen.ru/yandexmaps",
        "https://t.me/mapsyandex",
        "https://vk.com/yandex.maps",
        "https://vk.com/rtrg?p=VK-RTRG-1583133-ddikg",
        "https://vk.com/away.php?to=https://ya.cc/t/11VRxL_h3D3A7R&cc_key=",
        "https://ok.ru/friends",
    ]
    for url in invalid:
        assert canonical_social_url(url) == "", url

    assert canonical_social_url("https://dzen.ru/ddx_fitness") == "https://dzen.ru/ddx_fitness"
    assert canonical_social_url("https://t.me/ddx_fitness") == "https://t.me/ddx_fitness"
    assert canonical_social_url("https://vk.com/ddx_fitness") == "https://vk.com/ddx_fitness"
    assert canonical_social_url("https://ok.ru/ddx_fitness") == "https://ok.ru/ddx_fitness"


def test_website_social_finder_legacy_html_api():
    from yabiztracker.services.social_finder import WebsiteSocialFinder

    finder = WebsiteSocialFinder(None, SocialFinderConfig(validate_links=True))
    links = finder.extract_links_from_html(
        '<a href="https://vk.com/example">VK</a>'
        '<a href="https://t.me/example">Telegram</a>'
        '<a href="https://vk.com/wall-123_1">bad</a>'
    )
    assert links == {
        "vk": ["https://vk.com/example"],
        "telegram": ["https://t.me/example"],
    }


def test_website_social_finder_legacy_scan_signature_and_fetch(monkeypatch):
    from yabiztracker.services.social_finder import WebsiteSocialFinder

    finder = WebsiteSocialFinder(SocialFinderConfig(max_pages=2, respect_robots=False))
    html = (
        '<html><body>'
        '<a href="https://vk.com/cat">VK</a>'
        '<a href="https://max.ru/cat">MAX</a>'
        '<a href="/contacts">Контакты</a>'
        '</body></html>'
    )
    monkeypatch.setattr(finder, "_fetch", lambda url, robots: (html, url))
    monkeypatch.setattr(finder, "_validate", lambda url: True)

    result = finder.scan("1", "https://example.com")

    assert result.org_id == "1"
    assert result.status == "found"
    assert result.links == {
        "vk": ["https://vk.com/cat"],
        "max": ["https://max.ru/cat"],
    }
