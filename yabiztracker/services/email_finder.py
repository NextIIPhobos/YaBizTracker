from __future__ import annotations

import html
import logging
import re
import threading
from dataclasses import dataclass, field
from html.parser import HTMLParser
from queue import Empty, Queue
from urllib.parse import urljoin, urlparse, urlunparse
from urllib import robotparser

import requests

from ..domain.email import extract_emails, merge_emails

logger = logging.getLogger(__name__)

EMAIL_SCAN_STATUSES = ("not_scanned", "queued", "scanning", "found", "not_found", "error", "blocked", "no_website")


@dataclass(frozen=True)
class EmailFinderConfig:
    enabled: bool = True
    workers: int = 8
    max_pages: int = 5
    timeout_seconds: float = 12.0
    max_response_bytes: int = 2 * 1024 * 1024
    recheck_days: int = 30
    respect_robots: bool = True


@dataclass
class EmailScanResult:
    org_id: str
    emails: list[str] = field(default_factory=list)
    status: str = "not_found"
    error: str = ""
    pages: int = 0
    source_urls: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    """Extract visible text, mailto targets and same-site navigation links.

    Script/style contents are intentionally ignored for e-mail extraction:
    JavaScript bundles contain many strings that look like e-mail addresses
    but are not organization contacts (Sentry DSNs, asset URLs, package
    versions, image names, etc.).
    """

    _SKIP_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.mailto_values: list[str] = []
        self._anchor_href = ""
        self._anchor_text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            href = str(attrs_dict.get("href") or "").strip()
            self._anchor_href = href
            self._anchor_text = []
            if href.lower().startswith("mailto:"):
                self.mailto_values.append(href[7:])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._anchor_href:
            self.links.append((self._anchor_href, " ".join(self._anchor_text).strip()))
            self._anchor_href = ""
            self._anchor_text = []

    def handle_data(self, data):
        if self._skip_depth or not data:
            return
        self.text_parts.append(data)
        if self._anchor_href:
            self._anchor_text.append(data)


class WebsiteEmailFinder:
    """Bounded, cancellable website crawler used outside the GUI thread.

    Work is deduplicated by organization website before workers start, so one
    domain is crawled once even when thousands of organizations share it.
    """
    CONTACT_HINTS = ("contact", "contacts", "kontakt", "kontakty", "контакт", "контакты", "реквизит", "requisite", "about", "о-компании", "о компании", "information", "информация")
    CONTACT_PATHS = ("/contacts", "/contact", "/contacts/", "/contact/", "/information", "/information/", "/info", "/info/", "/kontakty", "/kontakty/", "/requisites", "/requisites/", "/about", "/about/", "/o-kompanii", "/o-kompanii/")
    SKIP_EXTENSIONS = re.compile(r"\.(?:pdf|jpg|jpeg|png|gif|webp|svg|zip|rar|7z|mp4|mp3|avi|docx?|xlsx?|pptx?)$", re.I)

    def __init__(self, db, config: EmailFinderConfig, logger_=None):
        self.db = db
        self.config = config
        self.logger = logger_ or logger
        self.stop_event = threading.Event()
        self._local = threading.local()

    def stop(self):
        self.stop_event.set()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "YaBizTracker/1.0 (+local business research tool)",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "ru,en;q=0.7",
            })
            self._local.session = session
        return session

    @staticmethod
    def _canonical_url(value: str) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        if not re.match(r"^https?://", value, re.I):
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return ""
        # Yandex often supplies tracking parameters. They should not affect
        # site identity or cause separate crawler jobs.
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))

    @staticmethod
    def _domain(value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return host[4:] if host.startswith("www.") else host

    def _robots(self, base_url: str):
        if not self.config.respect_robots:
            return None
        robots_url = urljoin(base_url, "/robots.txt")
        try:
            response = self._session().get(robots_url, timeout=self.config.timeout_seconds, allow_redirects=True)
            status = response.status_code
            body = response.text if 200 <= status < 300 else ""
            response.close()
            if status == 404:
                return None
            if not (200 <= status < 300):
                self.logger.warning("robots.txt недоступен для %s (HTTP %s); продолжаем без опубликованных правил", self._domain(base_url), status)
                return None
            rp = robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.parse(body.splitlines())
            return rp
        except requests.RequestException as exc:
            self.logger.warning("robots.txt недоступен для %s: %s; продолжаем без опубликованных правил", self._domain(base_url), exc)
            return None

    def _fetch(self, url: str, rp):
        if self.stop_event.is_set():
            raise RuntimeError("cancelled")
        if rp is False or (rp is not None and not rp.can_fetch("YaBizTracker", url)):
            raise PermissionError("robots.txt запретил доступ")
        response = self._session().get(url, timeout=self.config.timeout_seconds, allow_redirects=True, stream=True)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and "html" not in content_type and "xhtml" not in content_type:
            response.close()
            return "", ""
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if self.stop_event.is_set():
                response.close()
                raise RuntimeError("cancelled")
            total += len(chunk)
            if total > self.config.max_response_bytes:
                response.close()
                raise ValueError("страница превышает допустимый размер")
            chunks.append(chunk)
        raw = b"".join(chunks)
        encoding = response.encoding or response.apparent_encoding or "utf-8"
        response.close()
        try:
            return raw.decode(encoding, errors="replace"), response.url
        except (LookupError, UnicodeError):
            return raw.decode("utf-8", errors="replace"), response.url

    def _candidate_links(self, current_url: str, parser: _PageParser, base_domain: str):
        candidates = []
        seen = set()
        for href, label in parser.links:
            href = html.unescape(str(href or "")).strip()
            if not href or href.lower().startswith(("javascript:", "tel:", "mailto:", "#")):
                continue
            url = self._canonical_url(urljoin(current_url, href))
            if not url or self._domain(url) != base_domain or self.SKIP_EXTENSIONS.search(urlparse(url).path):
                continue
            haystack = f"{label} {href}".casefold()
            score = 0
            if any(hint in haystack for hint in self.CONTACT_HINTS):
                score += 10
            if urlparse(url).path in ("", "/"):
                score -= 2
            if url not in seen:
                seen.add(url)
                candidates.append((score, url))
        candidates.sort(key=lambda item: (-item[0], len(item[1])))
        return [url for _, url in candidates]

    def scan_website(self, org_id: str, website: str) -> EmailScanResult:
        start = self._canonical_url(website)
        if not start:
            return EmailScanResult(org_id, status="error", error="Некорректный URL сайта")
        rp = self._robots(start)
        if rp is False:
            return EmailScanResult(org_id, status="blocked", error="robots.txt недоступен; доступ запрещён в безопасном режиме")
        base_domain = self._domain(start)
        queue = [start]
        visited = set()
        emails = []
        source_urls = []
        pages = 0
        try:
            while queue and pages < max(1, self.config.max_pages) and not self.stop_event.is_set():
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                try:
                    text, final_url = self._fetch(url, rp)
                except PermissionError:
                    # A single blocked candidate page must not cancel the
                    # entire domain scan.
                    continue
                except requests.HTTPError as exc:
                    self.logger.info("Пропуск страницы %s: HTTP %s", url, getattr(exc.response, "status_code", "error"))
                    continue
                except requests.RequestException as exc:
                    self.logger.info("Пропуск страницы %s: %s", url, type(exc).__name__)
                    continue
                except Exception as exc:
                    self.logger.info("Пропуск страницы %s: %s", url, type(exc).__name__)
                    continue
                pages += 1
                if not text:
                    continue
                parser = _PageParser()
                try:
                    parser.feed(text)
                except Exception:
                    pass
                page_emails = extract_emails(text)
                # mailto links can contain percent-encoding and entities not
                # represented in visible HTML text.
                for href, _ in parser.links:
                    if href.lower().startswith("mailto:"):
                        page_emails.extend(extract_emails(href[7:]))
                merged = merge_emails(emails, page_emails)
                if merged:
                    emails = merged.split(", ")
                    source_urls.append(final_url or url)
                if pages < self.config.max_pages:
                    discovered = self._candidate_links(final_url or url, parser, base_domain)
                    # Modern sites can build navigation with JavaScript, so a
                    # contact link may be absent from raw HTML. Probe a small
                    # deterministic set of conventional information paths.
                    parsed_final = urlparse(final_url or url)
                    origin = f"{parsed_final.scheme}://{parsed_final.netloc}"
                    discovered.extend(self._canonical_url(urljoin(origin + "/", path.lstrip("/"))) for path in self.CONTACT_PATHS)
                    queue.extend(x for x in discovered if x and self._domain(x) == base_domain and x not in visited and x not in queue)
            if self.stop_event.is_set():
                return EmailScanResult(org_id, emails, "error", "Остановлено пользователем", pages, source_urls)
            return EmailScanResult(org_id, emails, "found" if emails else "not_found", "", pages, source_urls)
        except PermissionError as exc:
            return EmailScanResult(org_id, emails, "blocked", str(exc), pages, source_urls)
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            return EmailScanResult(org_id, emails, "blocked" if code in (401,403,429) else "error", f"HTTP {code or 'error'}", pages, source_urls)
        except requests.RequestException as exc:
            return EmailScanResult(org_id, emails, "error", f"Сетевая ошибка: {type(exc).__name__}", pages, source_urls)
        except Exception as exc:
            return EmailScanResult(org_id, emails, "error", f"{type(exc).__name__}: {exc}", pages, source_urls)

    def run(self, organizations: list[dict], on_result=None):
        # Group by domain: a shared corporate site is crawled once, then the
        # same discovered addresses are merged into every organization using it.
        groups = {}
        for org in organizations:
            org_id = org.get("org_id") or org.get("id")
            if not org_id:
                self.logger.warning("Пропуск организации без идентификатора: %s", org)
                continue
            website = self._canonical_url(org.get("website"))
            if website:
                normalized_org = dict(org)
                normalized_org["org_id"] = str(org_id)
                normalized_org["id"] = str(org_id)
                groups.setdefault(self._domain(website), {"website": website, "organizations": []})["organizations"].append(normalized_org)
        q = Queue()
        for item in groups.values():
            q.put(item)

        def worker():
            while not self.stop_event.is_set():
                try:
                    group = q.get_nowait()
                except Empty:
                    return
                try:
                    orgs = group["organizations"]
                    representative = orgs[0]
                    scanned = self.scan_website(str(representative["org_id"]), group["website"])
                    for org in orgs:
                        if self.stop_event.is_set():
                            break
                        result = EmailScanResult(
                            org_id=str(org["org_id"]),
                            emails=list(scanned.emails),
                            status=scanned.status,
                            error=scanned.error,
                            pages=scanned.pages,
                            source_urls=list(scanned.source_urls),
                        )
                        if on_result:
                            on_result(result)
                finally:
                    q.task_done()

        threads = []
        for _ in range(max(1, min(32, int(self.config.workers)))):
            t = threading.Thread(target=worker, name="email-finder", daemon=True)
            t.start(); threads.append(t)
        for t in threads:
            t.join()
        return True

