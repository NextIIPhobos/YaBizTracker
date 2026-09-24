from __future__ import annotations

import json
from typing import Any, Callable

from PyQt6.QtCore import QTimer, Qt


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

    def apply_state(self, organizations=None, fit_viewport: bool = False) -> None:
        if not self.is_ready():
            return
        cities = self.settings.get("cities", [])
        if organizations is None:
            names = [c.get("name", "") for c in cities]
            organizations = self.db.get_active_organizations(
                names, self.settings.get("period_days", 30)
            )
        self._js(
            f"setMapState({json.dumps(cities, ensure_ascii=False)},"
            f"{json.dumps(organizations, ensure_ascii=False)},"
            f"{int(self.settings.get('period_days', 30))},{str(bool(fit_viewport)).lower()});"
        )

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

    def fit_selection(self, table) -> None:
        """Fit the map to the organizations selected in the table.

        This method is called only for a genuine table-driven selection. Marker
        clicks deliberately bypass it so clicking a marker never moves the map.
        """
        if not self.is_ready():
            return
        organizations = []
        for index in table.visible_selected_rows():
            item = table.item(index.row(), self.org_column.NAME)
            if not item:
                continue
            oid = item.data(Qt.ItemDataRole.UserRole)
            if oid is None:
                continue
            org = self.db.get_by_id(str(oid))
            if org and org.get("latitude") is not None and org.get("longitude") is not None:
                organizations.append(org)
        self._js(f"fitOnOrganizations({json.dumps(organizations, ensure_ascii=False)});")

    def fit_after_selection_change(self, table) -> None:
        """Backward-compatible alias for explicit table selection fitting."""
        self.fit_selection(table)

    def schedule_selection_fit(self, table, delay: int = 50) -> None:
        QTimer.singleShot(delay, lambda: self.fit_selection(table))
