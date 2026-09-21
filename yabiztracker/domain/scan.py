from __future__ import annotations

import hashlib
import json


def _unique_casefolded(values):
    result = {str(value).strip().casefold() for value in values if str(value).strip()}
    return sorted(result)


def scan_signature(cities, categories, excluded_categories=None) -> str:
    """Create a stable identity for a search configuration."""
    city_values = sorted(
        ({"name": c.get("name", ""), "bbox": c.get("bbox", "")} for c in cities),
        key=lambda value: (str(value["name"]).casefold(), value["bbox"]),
    )
    category_values = _unique_casefolded(categories)
    excluded_values = _unique_casefolded(excluded_categories or [])
    payload = {
        "cities": city_values,
        "categories": category_values,
        "excluded_categories": excluded_values,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
