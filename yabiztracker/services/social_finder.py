from __future__ import annotations

import html
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)


SOCIAL_HOSTS = {
    "vk": ("vk.com", "vk.ru"),
    "telegram": ("t.me", "telegram.me", "telegram.dog"),
    "max": ("max.ru",),
    "instagram": ("instagram.com",),
    "ok": ("ok.ru", "odnoklassniki.ru"),
    "dzen": ("dzen.ru", "zen.yandex.ru"),
    "rutube": ("rutube.ru",),
    "youtube": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
    "facebook": ("facebook.com", "fb.com", "m.facebook.com"),
    "x": ("x.com", "twitter.com"),
    "threads": ("threads.net",),
    "pinterest": ("pinterest.com",),
    "linkedin": ("linkedin.com",),
    "viber": ("viber.com", "viber.click"),
    "whatsapp": ("wa.me", "whatsapp.com"),
    "discord": ("discord.gg", "discord.com"),
}

SOCIAL_LABELS = {
    "vk": "VK", "telegram": "Telegram", "max": "Max", "instagram": "Instagram",
    "ok": "Одноклассники", "dzen": "Дзен", "rutube": "Rutube", "youtube": "YouTube",
    "tiktok": "TikTok", "facebook": "Facebook", "x": "X/Twitter", "threads": "Threads",
    "pinterest": "Pinterest", "linkedin": "LinkedIn", "viber": "Viber",
    "whatsapp": "WhatsApp", "discord": "Discord",
}

URL_RE = re.compile(
    r"(?i)(?:(?:https?://|www\.)[^\s\"'<>]+|(?:vk\.com|vk\.ru|t\.me|telegram\.me|telegram\.dog|"
    r"max\.ru|instagram\.com|ok\.ru|odnoklassniki\.ru|dzen\.ru|zen\.yandex\.ru|rutube\.ru|"
    r"youtube\.com|youtu\.be|tiktok\.com|facebook\.com|fb\.com|x\.com|twitter\.com|threads\.net|"
    r"pinterest\.com|linkedin\.com|viber\.com|viber\.click|wa\.me|whatsapp\.com|discord\.gg|discord\.com)"
    r"/[^\s\"'<>]*)"
)

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid", "ysclid", "ref"}


@dataclass(frozen=True)
class SocialFinderConfig:
    enabled: bool = True
    workers: int = 8
    timeout_seconds: float = 10.0
    max_response_bytes: int = 3 * 1024 * 1024
    # ``website_pages`` is the current application setting. ``max_pages`` and
    # ``respect_robots`` are kept as compatibility fields for the legacy
    # WebsiteSocialFinder API and external integrations/tests.
    website_pages: int = 3
    validate_links: bool = True
    max_pages: int | None = None
    respect_robots: bool = True

    def __post_init__(self):
        if self.max_pages is not None:
            object.__setattr__(self, "website_pages", max(1, int(self.max_pages)))
        object.__setattr__(self, "website_pages", max(1, int(self.website_pages)))


@dataclass
class SocialScanResult:
    org_id: str
    links: dict[str, list[str]] = field(default_factory=dict)
    status: str = "not_found"
    error: str = ""
    sources: list[str] = field(default_factory=list)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() not in {"a", "link", "meta"}:
            return
        data = dict(attrs)
        for key in ("href", "content"):
            value = data.get(key)
            if value:
                self.hrefs.append(str(value))

    def handle_data(self, data):
        if data:
            self.text_parts.append(data)


def _decode_html(value: str) -> str:
    text = html.unescape(str(value or ""))
    for _ in range(2):
        text = text.replace("\\/", "/")
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        try:
            text = unquote(text)
        except Exception:
            pass
    return text


def platform_for_url(url: str) -> str | None:
    """Return a supported platform only for real social-network hosts.

    Do not accept arbitrary subdomains. In particular, VK pages contain many
    links to ``st.vk.ru``, ``login.vk.ru`` and ``papi.vk.ru`` assets which are
    not organization social profiles.
    """
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return None
    for platform, hosts in SOCIAL_HOSTS.items():
        if host in hosts or (host.startswith("www.") and host[4:] in hosts):
            return platform
    return None


_GENERIC_PROFILE_BLOCKLIST = {
    "vk": {"", "login", "logout", "away.php", "rtrg", "faq", "wall", "sticker", "usefull.php", "special.php",
           "settings", "feed", "search", "im", "friends", "groups", "video", "audio",
           "photos", "docs", "bookmarks", "notifications", "yandex", "yandex.maps", "yandexmaps",
           "maps", "mapsyandex"},
    "telegram": {"", "login", "auth", "faq", "blog", "mapsyandex", "yandex", "yandexmaps", "yandex_maps"},
    "max": {"", "login", "auth", "help", "support", "download"},
    "instagram": {"", "accounts", "explore", "direct", "about"},
    "ok": {"", "login", "dk", "help", "search", "friends", "messages", "notifications", "groups", "profile", "feed"},
    "dzen": {"", "yandexmaps", "yandex-maps", "yandex_maps", "yandexmapsru"},
    "rutube": {"", "search", "video", "play", "login"},
    "youtube": {"", "feed", "results", "watch", "shorts", "playlist", "signin", "login"},
    "tiktok": {"", "login", "explore", "search", "foryou"},
    "facebook": {"", "login", "help", "settings", "privacy", "policies"},
    "x": {"", "login", "home", "explore", "search", "settings", "i"},
    "threads": {"", "login", "search", "settings"},
    "pinterest": {"", "login", "search", "ideas", "settings"},
    "linkedin": {"", "login", "feed", "jobs", "learning", "mynetwork", "help"},
    "viber": {"", "download", "desktop", "blog"},
    "whatsapp": {"", "download", "features", "security", "privacy", "web", "business"},
    "discord": {"", "login", "register", "download", "developers", "safety"},
}

_ASSET_PATH_MARKERS = (
    "/css/", "/js/", "/dist/", "/fonts/", "/assets/", "/static/", "/chunks/",
    "/performance_", "/error_", ".css", ".js", ".woff", ".woff2", ".png", ".jpg", ".svg",
)


def _is_plausible_profile_url(url: str, platform: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = unquote(parsed.path or "/").replace("\\", "/")
    normalized = path.rstrip("/")
    segments = [seg for seg in normalized.split("/") if seg]
    first = segments[0].casefold() if segments else ""
    lower_path = normalized.casefold()
    if not segments or first in _GENERIC_PROFILE_BLOCKLIST.get(platform, set()):
        return False
    if any(marker in lower_path for marker in _ASSET_PATH_MARKERS):
        return False
    if platform == "vk":
        if host not in {"vk.com", "vk.ru"}:
            return False
        if parsed.query and any(k.lower() in {"act", "hash", "lrt", "_origin"} for k in (part.split("=",1)[0] for part in parsed.query.split("&"))):
            return False
        if first in {"m", "papi", "r3-test", "st"}:
            return False
        # VK content links are not organization profile/community links.
        if first in {"wall", "faq", "sticker", "usefull.php", "special.php"} or first.startswith(("wall-", "faq")):
            return False
        if first in {"club", "public", "id"}:
            return len(segments) >= 1 and bool(segments[0][len(first):])
        candidate = segments[0]
        if candidate.isdigit():
            return False
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", candidate):
            return False
        if candidate.casefold() in {"yandex", "yandex.maps", "yandexmaps", "maps"}:
            return False
        return len(segments) == 1
    if platform == "max":
        if host != "max.ru" or len(segments) != 1:
            return False
        candidate = segments[0]
        return bool(re.fullmatch(r"(?:@[a-zA-Z0-9_.-]{2,100}|[a-zA-Z0-9_.-]{2,100})", candidate))
    if platform in {"telegram", "instagram", "tiktok", "threads", "x", "pinterest", "linkedin"}:
        return len(segments) == 1 and len(segments[0]) >= 2
    if platform == "youtube":
        return first.startswith("@") or first in {"channel", "c", "user"}
    if platform == "viber":
        return len(segments) == 1 and bool(re.search(r"\d{6,}", segments[0]))
    if platform == "whatsapp":
        return first == "send" or (host == "wa.me" and bool(re.search(r"\d{7,}", first)))
    if platform == "discord":
        return first in {"invite"} or host == "discord.gg"
    # For the remaining networks, a non-generic first path segment is enough,
    # but the host itself must already be an exact supported host.
    return True


def canonical_social_url(value: str) -> str:
    value = _decode_html(str(value or "")).strip().strip(".,;:!?)]}>\\n\\r")
    # Extractors sometimes capture text after an URL (e.g. ``|руководством``).
    value = value.split("|", 1)[0].strip()
    if not value:
        return ""
    if value.startswith("www.") or not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    try:
        p = urlparse(value)
    except ValueError:
        return ""
    if p.scheme.lower() not in {"http", "https"} or not p.netloc:
        return ""
    platform = platform_for_url(value)
    if not platform or not _is_plausible_profile_url(value, platform):
        return ""
    query = "&".join(part for part in p.query.split("&") if part and part.split("=", 1)[0].lower() not in _TRACKING_PARAMS)
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urlunparse(("https", (p.hostname or "").lower(), path.rstrip("/") or "/", "", query, ""))

def extract_social_links(*texts: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    seen: set[str] = set()
    for raw in texts:
        text = _decode_html(raw)
        candidates = list(URL_RE.findall(text))
        try:
            parser = _LinkParser()
            parser.feed(text)
            candidates.extend(parser.hrefs)
        except Exception:
            pass
        for candidate in candidates:
            url = canonical_social_url(candidate)
            platform = platform_for_url(url)
            if not url or not platform or url in seen:
                continue
            seen.add(url)
            found.setdefault(platform, []).append(url)
    return found


def merge_social_links(*values) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            items = value.items()
        elif isinstance(value, (list, tuple, set)):
            items = [("other", value)]
        else:
            items = [("other", [value])]
        for platform, raw_values in items:
            if not isinstance(raw_values, (list, tuple, set)):
                raw_values = [raw_values]
            for raw in raw_values:
                url = canonical_social_url(str(raw or ""))
                if not url or url in seen:
                    continue
                seen.add(url)
                result.setdefault(str(platform), []).append(url)
    return result


def social_text(value) -> str:
    links = merge_social_links(value)
    return "; ".join(url for values in links.values() for url in values)


class SocialLinkFinder:
    """Find public social links from a Yandex Maps organization page and its site.

    The documented Yandex Organization Search API exposes the organization's
    website, but does not document social-network fields. Therefore this service
    treats social links as a separate enrichment step and never depends on
    undocumented Search API fields.
    """

    _CYRILLIC = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
        "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
        "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"e","Ж":"zh","З":"z","И":"i","Й":"y","К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f","Х":"h","Ц":"c","Ч":"ch","Ш":"sh","Щ":"sch","Ъ":"","Ы":"y","Ь":"","Э":"e","Ю":"yu","Я":"ya",
    })

    def __init__(self, db, config: SocialFinderConfig, logger_=None):
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
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 YaBizTracker/1.1.2",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
            })
            self._local.session = session
        return session

    @classmethod
    def yandex_maps_url(cls, name: str, org_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").translate(cls._CYRILLIC).lower()).strip("_") or "org"
        return f"https://yandex.ru/maps/org/{slug}/{org_id}/"

    def _fetch(self, url: str) -> tuple[str, str]:
        if self.stop_event.is_set():
            raise RuntimeError("cancelled")
        response = self._session().get(url, timeout=self.config.timeout_seconds, allow_redirects=True, stream=True)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and "html" not in content_type and "xhtml" not in content_type:
            response.close()
            return "", url
        chunks, total = [], 0
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
        final_url = response.url
        encoding = response.encoding or response.apparent_encoding or "utf-8"
        response.close()
        return raw.decode(encoding, errors="replace"), final_url

    def _validate(self, url: str) -> bool:
        if not self.config.validate_links:
            return True
        try:
            response = self._session().head(url, timeout=min(self.config.timeout_seconds, 8), allow_redirects=True)
            status = int(response.status_code)
            response.close()
            if status in {405, 429} or 200 <= status < 400:
                return True
            if status in {401, 403}:
                return True  # private/anti-bot pages can still be real links
            if status == 404 or status >= 500:
                return False
            return 200 <= status < 500
        except requests.RequestException:
            try:
                response = self._session().get(url, timeout=min(self.config.timeout_seconds, 8), allow_redirects=True, stream=True)
                status = int(response.status_code)
                response.close()
                return status != 404 and status < 500
            except requests.RequestException:
                return False

    def scan(self, org: dict) -> SocialScanResult:
        org_id = str(org.get("org_id") or org.get("id") or "").strip()
        if not org_id:
            return SocialScanResult("", status="error", error="Не указан ID организации")
        all_links: dict[str, list[str]] = {}
        sources: list[str] = []
        errors = []
        urls = [self.yandex_maps_url(org.get("name", ""), org_id)]
        website = str(org.get("website") or "").strip()
        if website:
            if not re.match(r"^https?://", website, re.I):
                website = "https://" + website
            urls.append(website)
        for source_index, source in enumerate(urls):
            if self.stop_event.is_set():
                return SocialScanResult(org_id, all_links, "cancelled", "", sources)
            queue = [source]
            visited = set()
            base_host = (urlparse(source).hostname or "").lower().removeprefix("www.")
            pages_left = 1 if source_index == 0 else max(1, self.config.website_pages)
            while queue and pages_left > 0:
                page_url = queue.pop(0)
                if page_url in visited:
                    continue
                visited.add(page_url)
                try:
                    body, final_url = self._fetch(page_url)
                    if not body:
                        continue
                    links = extract_social_links(body)
                    for platform, values in links.items():
                        all_links.setdefault(platform, []).extend(values)
                    sources.append(final_url)
                    pages_left -= 1
                    if source_index == 1 and pages_left > 0:
                        try:
                            parser = _LinkParser()
                            parser.feed(_decode_html(body))
                            candidates = []
                            for href in parser.hrefs:
                                absolute = urljoin(final_url, href)
                                parsed = urlparse(absolute)
                                host = (parsed.hostname or "").lower().removeprefix("www.")
                                if parsed.scheme not in {"http", "https"} or host != base_host:
                                    continue
                                haystack = absolute.casefold()
                                score = 0
                                if any(x in haystack for x in ("contact", "контакт", "about", "о-комп", "реквиз", "social", "связ")):
                                    score += 10
                                candidates.append((score, absolute))
                            for _, candidate in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
                                if candidate not in visited and candidate not in queue:
                                    queue.append(candidate)
                        except Exception:
                            pass
                except RuntimeError as exc:
                    if str(exc) == "cancelled":
                        return SocialScanResult(org_id, all_links, "cancelled", "", sources)
                    errors.append(str(exc))
                except requests.RequestException as exc:
                    errors.append(f"{page_url}: {exc}")
                except Exception as exc:
                    errors.append(f"{page_url}: {type(exc).__name__}: {exc}")
        merged = merge_social_links(all_links)
        if merged:
            validated: dict[str, list[str]] = {}
            for platform, values in merged.items():
                for url in values:
                    if self._validate(url):
                        validated.setdefault(platform, []).append(url)
            merged = validated
        if merged:
            return SocialScanResult(org_id, merged, "found", "; ".join(errors), sources)
        return SocialScanResult(org_id, {}, "error" if errors else "not_found", "; ".join(errors), sources)

    def run(self, organizations, on_result):
        candidates = list(organizations or [])
        if not candidates:
            return
        with ThreadPoolExecutor(max_workers=max(1, min(32, self.config.workers))) as executor:
            futures = {executor.submit(self.scan, org): org for org in candidates}
            for future in as_completed(futures):
                if self.stop_event.is_set():
                    break
                try:
                    on_result(future.result())
                except Exception as exc:
                    org = futures[future]
                    on_result(SocialScanResult(str(org.get("org_id") or org.get("id") or ""), {}, "error", str(exc), []))


class WebsiteSocialFinder(SocialLinkFinder):
    """Backward-compatible website-only social-link finder.

    The application now uses :class:`SocialLinkFinder`, but an earlier public
    API exposed ``WebsiteSocialFinder(config)``. Keep that API working so
    integrations/tests can be upgraded independently of the application.
    All extracted URLs still pass through the same canonical validator.
    """

    def __init__(self, db=None, config=None, logger_=None):
        # Legacy signature: WebsiteSocialFinder(config).
        if isinstance(db, SocialFinderConfig) and config is None:
            config = db
            db = None
        super().__init__(db, config or SocialFinderConfig(), logger_)

    def extract_links_from_html(self, html_text: str) -> dict[str, list[str]]:
        return extract_social_links(html_text)

    def _extract_links_from_html(self, html_text: str) -> dict[str, list[str]]:
        return self.extract_links_from_html(html_text)

    def extract_social_links(self, html_text: str) -> dict[str, list[str]]:
        return self.extract_links_from_html(html_text)

    def scan(self, org_or_id, website: str | None = None) -> SocialScanResult:
        """Support both the current organization-dict API and the legacy API.

        Current application code calls ``scan(org_dict)`` through
        :class:`SocialLinkFinder`. Older integrations called
        ``scan(org_id, website)`` on ``WebsiteSocialFinder``. Keeping both
        forms here prevents CI/external integrations from breaking while all
        links still use the same canonical validation path.
        """
        if isinstance(org_or_id, dict) and website is None:
            return super().scan(org_or_id)
        return self.scan_website(str(org_or_id or ""), str(website or ""))

    def _legacy_fetch(self, url: str):
        """Call legacy monkeypatched ``_fetch(url, robots)`` or current ``_fetch(url)``.

        Older integrations supplied a robots-parser argument to ``_fetch``.
        The current finder no longer needs that argument, but accepting the
        old callable shape here keeps the compatibility adapter genuinely
        backward-compatible without changing the current core API.
        """
        try:
            return self._fetch(url, None)
        except TypeError as exc:
            # Only retry when the callable rejects the legacy arity. Do not
            # turn arbitrary TypeErrors from the actual fetch into a second
            # request.
            message = str(exc).lower()
            if "positional" not in message and "argument" not in message:
                raise
            return self._fetch(url)

    def scan_website(self, org_id: str, website: str) -> SocialScanResult:
        """Scan only the supplied website using the legacy API shape."""
        website = str(website or "").strip()
        if not website:
            return SocialScanResult(str(org_id), {}, "no_website")
        if not re.match(r"^https?://", website, re.I):
            website = "https://" + website

        all_links: dict[str, list[str]] = {}
        sources: list[str] = []
        errors: list[str] = []
        queue = [website]
        visited: set[str] = set()
        base_host = (urlparse(website).hostname or "").lower().removeprefix("www.")
        pages_left = max(1, self.config.website_pages)

        while queue and pages_left > 0 and not self.stop_event.is_set():
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            try:
                body, final_url = self._legacy_fetch(page_url)
                if not body:
                    continue
                for platform, values in extract_social_links(body).items():
                    all_links.setdefault(platform, []).extend(values)
                sources.append(final_url)
                pages_left -= 1
                if pages_left > 0:
                    parser = _LinkParser()
                    parser.feed(_decode_html(body))
                    candidates = []
                    for href in parser.hrefs:
                        absolute = urljoin(final_url, href)
                        parsed = urlparse(absolute)
                        host = (parsed.hostname or "").lower().removeprefix("www.")
                        if parsed.scheme not in {"http", "https"} or host != base_host:
                            continue
                        candidates.append(absolute)
                    for candidate in candidates:
                        if candidate not in visited and candidate not in queue:
                            queue.append(candidate)
            except Exception as exc:
                errors.append(f"{page_url}: {type(exc).__name__}: {exc}")

        merged = merge_social_links(all_links)
        if merged and self.config.validate_links:
            merged = {
                platform: [url for url in values if self._validate(url)]
                for platform, values in merged.items()
            }
            merged = {platform: values for platform, values in merged.items() if values}
        if merged:
            return SocialScanResult(str(org_id), merged, "found", "; ".join(errors), sources)
        return SocialScanResult(str(org_id), {}, "error" if errors else "not_found", "; ".join(errors), sources)

    def find(self, website: str) -> dict[str, list[str]]:
        """Legacy convenience method returning links for one website."""
        return self.scan_website("", website).links
