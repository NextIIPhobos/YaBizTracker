from pathlib import Path
import tempfile

from yabiztracker.domain.email import extract_emails, merge_emails, normalize_email_list
from yabiztracker.database import Database
from yabiztracker.services.email_finder import WebsiteEmailFinder, EmailFinderConfig


def test_email_normalization_and_deduplication():
    assert normalize_email_list(" A@Example.COM, a@example.com; sales@example.com ") == ["a@example.com", "sales@example.com"]
    assert merge_emails("a@example.com", "B@Example.com, a@example.com") == "a@example.com, b@example.com"
    assert extract_emails("mailto:info@example.ru and sales@example.ru") == ["info@example.ru", "sales@example.ru"]


def test_database_merges_discovered_emails_and_keeps_history():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "organizations.db"))
        db.upsert_organizations([{
            "id": "1", "name": "Test", "address": "A", "category": "C",
            "website": "https://example.com", "email": "info@example.com",
            "social_links": "{}", "latitude": 0, "longitude": 0,
        }], "Самара")
        assert db.update_organization_emails("1", ["sales@example.com", "INFO@example.com"], "found", pages=3)
        row = db.get_by_id("1")
        assert row["email"] == "info@example.com, sales@example.com"
        hist = db.history("1")
        assert any(h["field"] == "email" and "sales@example.com" in h["new_value"] for h in hist)
        db.close()


def test_email_candidates_skip_recent_scan():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "organizations.db"))
        db.upsert_organizations([{
            "id": "1", "name": "Test", "website": "https://example.com",
            "email": "", "social_links": "{}", "latitude": 0, "longitude": 0,
        }], "Самара")
        assert len(db.get_email_scan_candidates(30)) == 1
        db.update_organization_emails("1", [], "not_found", pages=2)
        assert db.get_email_scan_candidates(30) == []
        db.close()


def test_domain_grouping_crawls_shared_site_once(monkeypatch):
    class DummyFinder(WebsiteEmailFinder):
        def __init__(self):
            super().__init__(None, EmailFinderConfig(workers=2))
            self.calls = []
        def scan_website(self, org_id, website):
            self.calls.append(website)
            from yabiztracker.services.email_finder import EmailScanResult
            return EmailScanResult(org_id, ["info@example.com", "sales@example.com"], "found", pages=2)

    f = DummyFinder(); results=[]
    f.run([
        {"id":"1", "website":"https://www.example.com"},
        {"id":"2", "website":"https://example.com/contacts"},
        {"id":"3", "website":"https://other.example.org"},
    ], results.append)
    assert len(f.calls) == 2
    assert len(results) == 3
    assert all(r.emails == ["info@example.com", "sales@example.com"] for r in results)


def test_website_parser_finds_multiple_emails_from_home_and_contacts(monkeypatch):
    finder = WebsiteEmailFinder(None, EmailFinderConfig(max_pages=3, respect_robots=False))
    pages = {
        "https://example.com": '<html><body>info@example.com<a href="/contacts">Контакты</a></body></html>',
        "https://example.com/contacts": '<a href="mailto:sales@example.com">sales</a> support@example.com',
    }
    def fake_fetch(url, rp):
        return pages[url], url
    monkeypatch.setattr(finder, "_fetch", fake_fetch)
    result = finder.scan_website("1", "https://example.com")
    assert result.status == "found"
    assert result.emails == ["info@example.com", "sales@example.com", "support@example.com"]


def test_email_finder_settings_have_safe_defaults():
    from yabiztracker.services.settings import migrate_settings
    cfg = migrate_settings({})["email_finder"]
    assert cfg["enabled"] is True
    assert cfg["workers"] == 8
    assert cfg["max_pages"] == 5
    assert cfg["respect_robots"] is True


def test_website_parser_handles_tracking_url_and_conventional_information_page(monkeypatch):
    finder = WebsiteEmailFinder(None, EmailFinderConfig(max_pages=5, respect_robots=False))
    pages = {
        "https://zdravcity.ru": '<html><body><nav>Меню</nav></body></html>',
        "https://zdravcity.ru/information": '<html><body>Контакты: <a href="mailto:24@zdravcity.ru">24@zdravcity.ru</a></body></html>',
    }
    def fake_fetch(url, rp):
        if url not in pages:
            from requests import HTTPError
            response = type("Response", (), {"status_code": 404})()
            err = HTTPError(response=response)
            raise err
        return pages[url], url
    monkeypatch.setattr(finder, "_fetch", fake_fetch)
    result = finder.scan_website("1", "https://zdravcity.ru/?utm_campaign=organic_globus&utm_medium=static&utm_source=yandex_karty")
    assert result.status == "found"
    assert result.emails == ["24@zdravcity.ru"]
    assert "https://zdravcity.ru/information" in result.source_urls


def test_manual_scan_records_accept_ui_id_shape():
    class DummyFinder(WebsiteEmailFinder):
        def __init__(self):
            super().__init__(None, EmailFinderConfig(workers=1))
            self.seen = []
        def scan_website(self, org_id, website):
            self.seen.append((org_id, website))
            from yabiztracker.services.email_finder import EmailScanResult
            return EmailScanResult(org_id, ["info@example.com"], "found", pages=1)

    f = DummyFinder(); results = []
    f.run([{"id": "123", "name": "Test", "website": "https://example.com"}], results.append)
    assert f.seen == [("123", "https://example.com")]
    assert results[0].org_id == "123"


def test_extract_emails_does_not_take_urls_scripts_or_asset_names():
    source = """
    /75b6a20df0014dbc8cf4d074eeeea6c5@stacks.vk-portal.net
    //d6e663a43b37aa5393452888c008fea9@sentry.userecho.com
    u003epersonal-data@yandex-team.ru
    //striksi.ru/politika/info@striksi.ru
    //static.zdravcity.ru/img/home/capabilities/capabilities-laptop-1@2x.png
    +620146/@56.7973159
    <script>const x='keyboard-support@yandex-team.ru';</script>
    <style>.x{content:'info@fake.example.ru'}</style>
    Visible: personal-data@yandex-team.ru, info@striksi.ru
    """
    assert extract_emails(source) == ["personal-data@yandex-team.ru", "info@striksi.ru"]


def test_html_email_extraction_ignores_script_style_and_asset_urls():
    finder = WebsiteEmailFinder(None, EmailFinderConfig(max_pages=1, respect_robots=False))
    html = """
    <html><body>
      <a href="mailto:info@example.ru">info@example.ru</a>
      <div>sales@example.ru</div>
      <img src="//static.example.ru/assets/laptop@2x.png">
      <script>const email = 'fake@example.ru';</script>
      <script src="https://cdn.example.ru/bundle@2x.js"></script>
    </body></html>
    """
    def fake_fetch(url, rp):
        return html, url
    finder._fetch = fake_fetch
    result = finder.scan_website("1", "https://example.ru")
    assert result.emails == ["info@example.ru", "sales@example.ru"]


def test_database_migration_cleans_legacy_false_positive_emails():
    import sqlite3
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "organizations.db"
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version=8")
        conn.executescript("""
        CREATE TABLE organizations(
          org_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT,
          category TEXT, subcategory TEXT, phone TEXT, website TEXT,
          email TEXT, social_links TEXT, latitude REAL, longitude REAL,
          first_seen_date TEXT NOT NULL, last_updated TEXT, city_name TEXT,
          status TEXT, comment TEXT, responsible TEXT, next_contact_date TEXT,
          last_seen_at TEXT, missing_scan_count INTEGER, source_status TEXT,
          categories_json TEXT, email_scan_status TEXT, email_scanned_at TEXT,
          email_scan_error TEXT, email_scan_pages INTEGER
        );
        """)
        conn.execute("INSERT INTO organizations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "1", "Test", "", "", "", "", "https://example.ru",
            "//static.example.ru/x@2x.png, info@example.ru, /policy/info@example.ru",
            "{}", 0, 0, "2026-01-01", "", "", "Новый", "", "", "", "", 0,
            "unknown", "[]", "not_scanned", "", "", 0
        ))
        conn.commit(); conn.close()
        db = Database(str(path))
        assert db.get_by_id("1")["email"] == "info@example.ru"
        db.close()


def test_email_validation_rejects_masked_addresses_package_versions_and_escaped_artifacts():
    raw = "bundler=rspack@1.6.8, ol************9@list.ru, kr*********8@rambler.ru, u003egdpr@yandex-team.ru, office@meitanglobal.com"
    assert normalize_email_list(raw) == ["gdpr@yandex-team.ru", "office@meitanglobal.com"]


def test_email_validation_rejects_markup_fragments_and_asset_filenames():
    raw = """
    content='office@meitanglobal.com, managermsk1@meitan.ru
    content='12olga_la@mail.ru, iperemin163@bk.ru
    &emailto=`club112samara@mail.ru, &emailfrom=`noreply@112club.ru
    krismirsamara@mail.ru, &emailto=`krismirsamara@mail.ru, krismir12@mail.ru
    link}passwd_lc@corp.mail.ru, info@sferum.ru
    <!--rating@mail.ru, rating@mail.ru, 9229156@gmail.com
    olimp-sppo@mail.ru, &ldienulm-_hwk=@wmilvcot.taq, lznspo@mail.ru
    3@3x.png
    """
    assert normalize_email_list(raw) == [
        "office@meitanglobal.com", "managermsk1@meitan.ru",
        "12olga_la@mail.ru", "iperemin163@bk.ru",
        "club112samara@mail.ru", "noreply@112club.ru",
        "krismirsamara@mail.ru", "krismir12@mail.ru",
        "info@sferum.ru", "rating@mail.ru", "9229156@gmail.com",
        "olimp-sppo@mail.ru", "lznspo@mail.ru",
    ]
