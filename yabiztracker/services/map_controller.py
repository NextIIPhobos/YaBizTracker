from __future__ import annotations

import json
from typing import Any, Callable

from PyQt6.QtCore import QTimer, Qt
from ..domain.filters import matches_organization_filters


class MapController:
    """Single owner of the Python -> JavaScript map viewport contract.

    Organization API health, quota checks and table refreshes never decide the
    viewport. The controller sends one coherent map state and explicit fit
    commands for settlement/organization selection.
    """

    def __init__(self, webview, is_ready: Callable[[], bool], settings: dict, db: Any, org_column: Any):
        self.webview = webview
        self.is_ready = is_ready
        self.settings = settings
        self.db = db
        self.org_column = org_column

    def _js(self, expression: str) -> None:
        if self.is_ready():
            self.webview.page().runJavaScript(expression)

    def apply_state(self, category_names=None) -> None:
        if not self.is_ready():
            return
        cities = self.settings.get("cities", [])
        names = [c.get("name", "") for c in cities]
        orgs = self.db.get_active_organizations(names, self.settings.get("period_days", 30))
        if category_names is not None:
            orgs = [org for org in orgs if matches_organization_filters(org, {"category_names": category_names})]
        self._js(f"setMapState({json.dumps(cities, ensure_ascii=False)},{json.dumps(orgs, ensure_ascii=False)},{int(self.settings.get('period_days', 30))});")

    def fit_settlements(self) -> None:
        if not self.is_ready():
            return
        cities = self.settings.get("cities", [])
        self._js(f"fitToSettlements({json.dumps(cities, ensure_ascii=False)});")


    def sync_selection(self, table) -> None:
        """Keep map marker selection styling synchronized with the visible table selection."""
        if not self.is_ready():
            return
        ids = []
        for index in table.visible_selected_rows():
            item = table.item(index.row(), self.org_column.NAME)
            if item:
                oid = item.data(Qt.ItemDataRole.UserRole)
                if oid is not None:
                    ids.append(str(oid))
        self._js(f"setSelectedMarkers({json.dumps(ids, ensure_ascii=False)});")

    def fit_after_selection_change(self, table) -> None:
        if not self.is_ready():
            return
        rows = table.visible_selected_rows()
        if not rows:
            self.fit_settlements()
            return
        orgs = []
        for index in rows:
            item = table.item(index.row(), self.org_column.NAME)
            if not item:
                continue
            org = self.db.get_by_id(item.data(Qt.ItemDataRole.UserRole))
            if org and org.get("latitude") is not None and org.get("longitude") is not None:
                orgs.append(org)
        if orgs:
            self._js(f"fitOnOrganizations({json.dumps(orgs, ensure_ascii=False)});")

    def schedule_selection_fit(self, table, delay: int = 50) -> None:
        QTimer.singleShot(delay, lambda: self.fit_after_selection_change(table))
