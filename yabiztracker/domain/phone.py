"""Phone parsing and messenger link construction."""
from __future__ import annotations

import re
from urllib.parse import quote


def split_phone_values(value: str | None) -> list[str]:
    """Split the stored multi-phone field into unique display values."""
    result: list[str] = []
    for part in re.split(r"[;,\n]+", str(value or "")):
        part = part.strip()
        if part and part not in result:
            result.append(part)
    return result


def normalize_ru_phone(value: str | None) -> str | None:
    """Return a Russian phone in international +7XXXXXXXXXX form.

    Normalization is intentionally performed at the integration boundary where
    a phone is used to construct an external messenger URL, not persisted back
    into the database. This preserves the source value shown to marketers.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        return None
    return "+" + digits


def messenger_url(messenger: str, phone: str) -> str | None:
    normalized = normalize_ru_phone(phone)
    if not normalized:
        return None
    encoded = quote(normalized, safe="+")
    digits = normalized[1:]
    templates = {
        "Telegram": f"https://t.me/{encoded}",
        "WhatsApp": f"https://wa.me/{encoded}",
        "Viber": f"https://viber.click/{digits}",
        "Max": f"https://max.ru/{encoded}",
    }
    return templates.get(messenger)
