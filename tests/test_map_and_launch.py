from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MapAndLaunchStaticTests(unittest.TestCase):
    def test_map_has_deterministic_search_city_centering(self):
        text = (ROOT / "yabiztracker" / "map.html").read_text(encoding="utf-8")
        self.assertIn("function setMapLocations(cities)", text)
        self.assertIn("cityPoints", text)
        self.assertIn("function setMapState(cities,organizations,periodDays)", text)
        self.assertIn("function fitToSettlements(cities)", text)
        self.assertIn("function fitOnOrganizations(organizations)", text)
        self.assertIn("myMap.setCenter(points[0],15", text)
        self.assertIn("window.pendingMapCities", text)
        self.assertIn("applyPendingMapCities", text)

    def test_launchers_are_not_responsible_for_selection_behavior(self):
        # Launchers must only choose an executable/source entry point; Qt table
        # selection is implemented in the application, not in a wrapper script.
        for name in ("run.bat", "run.vbs"):
            text = (ROOT / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("selectmode", text)
            self.assertNotIn("selectionmode", text)

    def test_windows_build_runs_tests_before_pyinstaller(self):
        text = (ROOT / "build_windows.bat").read_text(encoding="utf-8").lower()
        self.assertIn("pytest -q tests", text)
        self.assertLess(text.index("pytest -q tests"), text.index("pyinstaller --clean"))


if __name__ == "__main__":
    unittest.main()


class MapViewportContractTests(unittest.TestCase):
    def test_search_api_health_is_not_in_map_viewport_path(self):
        text = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("on_health_search", text[text.index("def on_map_ready"):text.index("def run_health")])

    def test_selection_fit_is_explicitly_debounced(self):
        text = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("self._selection_map_timer.start(50)", text)
        self.assertIn("fit_after_selection_change", (ROOT / "yabiztracker" / "services" / "map_controller.py").read_text(encoding="utf-8"))

    def test_map_marker_colors_use_monitoring_period_and_selection_is_persistent(self):
        text = (ROOT / "yabiztracker" / "map.html").read_text(encoding="utf-8")
        self.assertIn("function markerColor(age,periodDays)", text)
        self.assertIn("currentPeriodDays", text)
        self.assertIn("function setSelectedMarkers(ids)", text)
        self.assertIn("zIndex:selected?10000:100", text)
        self.assertIn("markerLayouts.selected", text)
        self.assertNotIn("function markerColor(age){", text)

    def test_python_map_controller_sends_monitoring_period_and_selection(self):
        text = (ROOT / "yabiztracker" / "services" / "map_controller.py").read_text(encoding="utf-8")
        self.assertIn("setMapState(", text)
        self.assertIn("period_days", text)
        self.assertIn("def sync_selection(self, table)", text)
        self.assertIn("setSelectedMarkers", text)


class V111MapContractTests(unittest.TestCase):
    def test_marker_click_bridge_and_selected_visual_contract(self):
        text = (ROOT / "yabiztracker" / "map.html").read_text(encoding="utf-8")
        bridge = (ROOT / "yabiztracker" / "bridge.py").read_text(encoding="utf-8")
        assert "m.events.add('click'" in text
        assert "onMarkerClicked(key)" in text
        assert "markerLayouts.selected" in text
        assert "selected?" in text and "m.properties.set('markerColor',selected?'#FF0000'" in text
        assert "zIndex:selected?10000:100" in text
        assert "def onMarkerClicked" in bridge


    def test_marker_click_has_explicit_hit_shape_local_selection_and_bridge_fallback(self):
        text = (ROOT / "yabiztracker" / "map.html").read_text(encoding="utf-8")
        ui = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        assert "function notifyMarkerClicked(id)" in text
        assert "window.bridge" in text
        assert "iconShape:{type:'Circle'" in text
        assert "selectedMarkerIds=new Set([key])" in text
        assert "return false" in text
        assert "setCurrentCell(r,OrgColumn.NAME" in ui
        assert "SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows" in ui

    def test_map_state_is_sent_from_filtered_table_rows(self):
        ui = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        assert "def _filtered_organizations" in ui
        assert "self.map_controller.apply_state(self._filtered_organizations())" in ui

    def test_status_is_multiselect_and_checkbox_filters_are_committed(self):
        ui = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        widgets = (ROOT / "yabiztracker" / "ui" / "widgets.py").read_text(encoding="utf-8")
        assert 'CheckableDropdown("Статусы")' in ui
        assert "committed.connect(self.on_checkbox_filters_committed)" in ui
        assert "popup.closed.connect(self._popup_closed)" in widgets
        assert "self._dirty = True" in widgets

    def test_category_catalog_sync_is_wired_after_scan_and_to_help(self):
        ui = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        service = (ROOT / "yabiztracker" / "services" / "category_catalog.py").read_text(encoding="utf-8")
        assert 'Проверка доступных категорий' in ui
        assert "self.check_available_categories(log_only=True)" in ui
        assert "append_missing_categories" in service

    def test_version_is_111_everywhere_core(self):
        assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.1"
        assert 'version = "1.1.1"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert '__version__="1.1.1"' in (ROOT / "yabiztracker" / "__init__.py").read_text(encoding="utf-8")

class MarkerClickViewportTests(unittest.TestCase):
    def test_marker_click_does_not_schedule_map_viewport_fit(self):
        text = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        start = text.index("    def marker_selected(self,oid):")
        end = text.index("    def on_map_ready(self):", start)
        block = text[start:end]
        assert "self._selection_map_timer.stop()" in block
        assert "self._suppress_selection_map_fit=True" in block
        assert "self.org_table.scrollToItem(it)" in block
        assert "fit_after_selection_change" not in block
        assert "fitOnOrganizations" not in block

    def test_selection_changed_suppresses_fit_during_marker_click(self):
        text = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        start = text.index("    def selection_changed(self):")
        end = text.index("    def crm_changed", start)
        block = text[start:end]
        assert "_suppress_selection_map_fit" in block
        assert "self._selection_map_timer.stop()" in block
        assert "self._selection_map_timer.start(50)" in block
        assert "self.map_controller.sync_selection(self.org_table)" in block
