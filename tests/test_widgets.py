import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QTableWidgetItem
    from yabiztracker.ui.widgets import CheckableDropdown, OrganizationTableWidget
except ImportError:
    QApplication = None
    CheckableDropdown = None
    OrganizationTableWidget = None



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

    def test_column_chooser_uses_a_popup_that_closes_only_outside_its_area(self):
        widget = CheckableDropdown("Отображаемые столбцы")
        widget.set_items(["Название", "Адрес"], {"Название", "Адрес"})
        self.assertTrue(widget._popup.windowFlags() & Qt.WindowType.Popup)
        widget._toggle_popup()
        self.assertTrue(widget._popup.isVisible())


@unittest.skipIf(QApplication is None, "PyQt6 is not installed in the audit environment")
class OrganizationTableSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _table(self):
        table = OrganizationTableWidget(5, 1)
        for row in range(table.rowCount()):
            item = QTableWidgetItem(f"Organization {row}")
            item.setData(Qt.ItemDataRole.UserRole, str(row))
            table.setItem(row, 0, item)
        return table

    def test_shift_range_keeps_anchor_when_target_is_above_it(self):
        table = self._table()
        table.select_visible_range(4, 1)
        self.assertEqual([index.row() for index in table.visible_selected_rows()], [1, 2, 3, 4])
        self.assertEqual(table.currentRow(), 1)

    def test_shift_range_skips_hidden_rows_without_crashing(self):
        table = self._table()
        table.setRowHidden(2, True)
        table.select_visible_range(4, 0)
        self.assertEqual([index.row() for index in table.visible_selected_rows()], [0, 1, 3, 4])


if __name__ == "__main__":
    unittest.main()
