import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
try:
    from PyQt6.QtWidgets import QApplication
    from yabiztracker.ui.widgets import CheckableDropdown
except ModuleNotFoundError:
    QApplication = None
    CheckableDropdown = None



@unittest.skipIf(QApplication is None, "PyQt6 is not installed in the audit environment")
class CheckableDropdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_configured_settlements_are_rendered_as_checkboxes(self):
        widget = CheckableDropdown("Населённый пункт")
        widget.set_items(["Самара", "Тольятти", "Самара"])
        self.assertEqual(set(widget._items), {"Самара", "Тольятти"})
        self.assertEqual(widget.checked_values(), set())

    def test_checked_values_roundtrip_and_select_all(self):
        widget = CheckableDropdown("Населённый пункт")
        widget.set_items(["Самара", "Тольятти"])
        widget._set_all(True)
        self.assertEqual(widget.checked_values(), {"Самара", "Тольятти"})
        widget._set_all(False)
        self.assertEqual(widget.checked_values(), set())

    def test_refresh_drops_stale_settlement_values(self):
        widget = CheckableDropdown("Населённый пункт")
        widget.set_items(["Самара", "Тольятти"])
        widget._set_all(True)
        widget.set_items(["Самара"], {"Самара", "Тольятти"})
        self.assertEqual(widget.checked_values(), {"Самара"})


if __name__ == "__main__":
    unittest.main()
