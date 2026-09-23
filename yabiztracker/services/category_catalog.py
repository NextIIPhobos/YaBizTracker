from __future__ import annotations

import json

from ..domain.categories import append_missing_categories


def sync_category_catalog(db, path: str) -> list[str]:
    """Add every previously unseen organization category to the user catalog."""
    raw_values = []
    for org in db.get_all_organizations():
        raw = org.get("categories_json")
        try:
            values = json.loads(raw or "[]")
        except (TypeError, ValueError):
            values = []
        if not isinstance(values, list):
            values = [org.get("category"), org.get("subcategory")]
        raw_values.extend(str(value).strip() for value in values if str(value).strip())
    return append_missing_categories(path, raw_values)
