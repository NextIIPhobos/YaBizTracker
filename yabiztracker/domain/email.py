from __future__ import annotations

import re
from html import unescape
from urllib.parse import unquote

# Deliberately require a real-looking domain and forbid URL/path characters at
# both sides. The latter is important when scanning HTML: strings such as
# //static.site/image@2x.png or /policy/info@example.ru are not e-mail
# addresses even though a naive e-mail regex would find a substring in them.
_EMAIL_PATTERN = r"[a-z0-9](?:[a-z0-9._%+\-]*[a-z0-9])?@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
EMAIL_RE = re.compile(
    rf"(?i)(?<![a-z0-9_!#$%*+/=?^{{|}}~.\-/])({_EMAIL_PATTERN})(?![a-z0-9_!#$%&'*+/=?^{{|}}~.\-/])"
)
EMAIL_FULL_RE = re.compile(rf"(?i)^{_EMAIL_PATTERN}$")

# Common template placeholders. They are syntactically valid addresses but
# are not useful organization contacts and occur frequently in web templates.
_PLACEHOLDER_EMAILS = {
    "your@email.com",
    "your@email.ru",
    "name@example.com",
    "email@example.com",
    "test@example.com",
}


def normalize_email(value: str) -> str:
    value = unescape(unquote(str(value or "")))
    value = re.sub(r"u003[eE]", ">", value)
    value = re.sub(r"u003[cC]", "<", value)
    value = value.strip().strip("<>[](){}\"\'. ,;:")
    return value.casefold()

def is_valid_email(value: str) -> bool:
    email = normalize_email(value)
    if not email or email in _PLACEHOLDER_EMAILS:
        return False
    if not EMAIL_FULL_RE.fullmatch(email):
        return False
    # A valid address cannot contain URL/path separators. Keep this explicit
    # even though the regex already rejects them, because this function is
    # also used to sanitize legacy database values.
    if any(ch in email for ch in ("/", "\\", "?", "#")):
        return False
    # Masked addresses copied from public pages (e.g. ol********9@list.ru)
    # are not actionable contacts and should never enter the CRM.
    if "*" in email:
        return False
    local, domain = email.rsplit("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        return False
    if ".." in local or ".." in domain:
        return False
    # Reject package/version strings such as bundler=rspack@1.6.8.
    # Public e-mail domains have a non-numeric TLD.
    tld = domain.rsplit(".", 1)[-1]
    if not re.fullmatch(r"[a-z]{2,63}", tld, re.IGNORECASE):
        return False
    if tld.lower() in {
        "png", "jpg", "jpeg", "gif", "webp", "svg", "ico",
        "css", "js", "map", "json", "xml", "woff", "woff2",
        "ttf", "eot", "mp4", "webm",
    }:
        return False
    return True


def normalize_email_list(value) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, (list, tuple, set)) else [str(value)]
    result = []
    seen = set()
    for item in raw_items:
        text = str(item or "")
        # Use the same context-aware extractor for legacy/database values. This
        # strips HTML/JS prefixes such as content=' and &emailto=` instead of
        # treating them as part of the address.
        candidates = extract_emails(text)
        if not candidates:
            candidates = [normalize_email(text)]
        for email in candidates:
            email = normalize_email(email)
            if not is_valid_email(email) or email in seen:
                continue
            seen.add(email)
            result.append(email)
    return result


def extract_emails(text: str) -> list[str]:
    """Extract e-mails from plain text, not from arbitrary URL fragments."""
    source = unescape(unquote(str(text or "")))
    # Broken JSON/JS escaping is sometimes exposed as literal u003c/u003e
    # text by web pages. Treat it as markup punctuation, not part of an address.
    source = re.sub(r"u003[eE]", ">", source)
    source = re.sub(r"u003[cC]", "<", source)
    found = []
    seen = set()
    for match in EMAIL_RE.finditer(source):
        email = normalize_email(match.group(1))
        if is_valid_email(email) and email not in seen:
            seen.add(email)
            found.append(email)
    return found


def merge_emails(*values) -> str:
    result = []
    seen = set()
    for value in values:
        for email in normalize_email_list(value):
            if email not in seen:
                seen.add(email)
                result.append(email)
    return ", ".join(result)
