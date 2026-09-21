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
