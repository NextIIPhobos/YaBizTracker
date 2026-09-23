from __future__ import annotations

import re
from urllib.parse import urlparse

# Broad set of social/community platforms commonly present in Russian business profiles.
SOCIAL_DOMAINS = {
    "vk": ("vk.com", "vk.ru", "m.vk.com"),
    "telegram": ("t.me", "telegram.me", "telegram.dog"),
    "max": ("max.ru",),
    "ok": ("ok.ru", "odnoklassniki.ru"),
    "instagram": ("instagram.com", "instagr.am"),
    "facebook": ("facebook.com", "fb.com", "m.facebook.com"),
    "youtube": ("youtube.com", "youtu.be", "m.youtube.com"),
    "rutube": ("rutube.ru",),
    "dzen": ("dzen.ru", "zen.yandex.ru"),
    "tiktok": ("tiktok.com", "vm.tiktok.com"),
    "threads": ("threads.net",),
    "x": ("x.com", "twitter.com"),
    "linkedin": ("linkedin.com",),
    "pinterest": ("pinterest.com", "pin.it"),
    "tenchat": ("tenchat.ru",),
    "vc": ("vc.ru",),
    "reddit": ("reddit.com",),
    "twitch": ("twitch.tv",),
    "discord": ("discord.com", "discord.gg"),
    "patreon": ("patreon.com",),
}
_DOMAIN_TO_KEY = {d: k for k, ds in SOCIAL_DOMAINS.items() for d in ds}
_URL_RE = re.compile(r'https?://[^\s<>()\[\]{}"\']+', re.I)


def social_key(url: str) -> str | None:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return None
    for domain, key in _DOMAIN_TO_KEY.items():
        if host == domain or host.endswith("." + domain):
            return key
    return None


def normalize_social_url(value: str) -> str:
    value = str(value or "").strip().strip('.,;:!?)\"]\'')
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    elif not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value


def _walk_links(value):
    if isinstance(value, str):
        for m in _URL_RE.findall(value):
            yield m
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_links(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _walk_links(v)


def extract_social_links(*values) -> dict[str, list[str]]:
    """Extract and classify social URLs from arbitrary Yandex/API structures.

    Values are intentionally traversed recursively because the documented
    Organization Search API does not document a social-links field. If Yandex
    returns extra link metadata, it is used opportunistically; the website
    scanner provides the supported fallback for organizations whose profile
    does not expose such links.
    """
    out: dict[str, list[str]] = {}
    seen = set()
    for value in values:
        for raw in _walk_links(value):
            url = normalize_social_url(raw)
            key = social_key(url)
            if not key or url in seen:
                continue
            seen.add(url)
            out.setdefault(key, []).append(url)
    return out
