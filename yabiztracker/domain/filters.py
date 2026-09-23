from __future__ import annotations

import json
from collections.abc import Mapping


def normalize_category(value: object) -> str:
    return " ".join(str(value or "").replace("ё", "е").replace("Ё", "Е").split()).casefold()


def organization_categories(org: Mapping) -> set[str]:
    """Return all known category names for an organization in canonical form."""
    raw = org.get("categories_json")
    categories: list[object] = []
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                categories.extend(parsed)
        except (TypeError, ValueError):
            pass

    if not categories:
        categories.extend((org.get("category"), org.get("subcategory")))
    return {normalize_category(value) for value in categories if normalize_category(value)}


def excluded_category_match(org: Mapping, excluded_categories) -> bool:
    excluded = {
        normalize_category(value)
        for value in (excluded_categories or [])
        if normalize_category(value)
    }
    return bool(excluded and organization_categories(org) & excluded)


def _has_contact_value(org: Mapping, field: str) -> bool:
    """Return whether a contact/CRM field contains a meaningful value.

    Social links are stored as JSON. An empty object (``{}``) must count as
    missing even though its string representation is non-empty.
    """
    raw = org.get(field)
    if field == "social_links":
        if raw is None:
            return False
        if isinstance(raw, Mapping):
            return bool(raw)
        text = str(raw).strip()
        if not text or text in {"{}", "[]", "null"}:
            return False
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return bool(text)
        return bool(parsed)
    return bool(str(raw or "").strip())


def matches_organization_filters(org: Mapping, filters: Mapping | None = None) -> bool:
    """Pure predicate shared by UI filtering and non-SQL consumers."""
    filters = filters or {}
    search = str(filters.get("search") or "").strip().casefold()
    if search:
        provided_values = filters.get("search_values")
        if provided_values is not None:
            haystack = tuple(str(value or "").casefold() for value in provided_values)
        else:
            haystack = (
                str(org.get("name") or "").casefold(),
                str(org.get("address") or "").casefold(),
                str(org.get("city_name") or "").casefold(),
                str(org.get("category") or "").casefold(),
                str(org.get("subcategory") or "").casefold(),
            )
        if not any(search in value for value in haystack):
            return False

    if "category_names" in filters:
        selected_categories = {
            normalize_category(value)
            for value in (filters.get("category_names") or [])
            if normalize_category(value)
        }
        # An explicitly empty category selection means that the user turned
        # every category off. Omitting the key remains the unfiltered state.
        if not selected_categories:
            return False
        if organization_categories(org).isdisjoint(selected_categories):
            return False
    else:
        category = str(filters.get("category") or "")
        if category:
            wanted = normalize_category(category)
            if wanted not in organization_categories(org):
                return False

    if "status_names" in filters:
        selected_statuses = {
            str(value).strip()
            for value in (filters.get("status_names") or [])
            if str(value).strip()
        }
        if not selected_statuses:
            return False
        if str(org.get("status") or "").strip() not in selected_statuses:
            return False
    else:
        status = str(filters.get("status") or "")
        if status and str(org.get("status") or "") != status:
            return False

    selected_cities = {
        str(value).strip().casefold()
        for value in (filters.get("city_names") or [])
        if str(value).strip()
    }
    if selected_cities and str(org.get("city_name") or "").strip().casefold() not in selected_cities:
        return False

    field_modes = (
        ("phone_mode", "phone"),
        ("email_mode", "email"),
        ("website_mode", "website"),
        ("social_mode", "social_links"),
        ("responsible_mode", "responsible"),
        ("next_contact_mode", "next_contact_date"),
    )
    for mode_key, field in field_modes:
        mode = str(filters.get(mode_key) or "all")
        if mode not in {"all", "has", "missing"}:
            mode = "all"
        has_value = _has_contact_value(org, field)
        if mode == "has" and not has_value:
            return False
        if mode == "missing" and has_value:
            return False

    return True
