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
        self.assertEqual(widget.checked_values(), {"Самара", "Тольятти"})

    def test_checked_values_roundtrip_and_select_all(self):
        widget = CheckableDropdown("Населённый пункт")
        widget.set_items(["Самара", "Тольятти"])
        widget._set_all(True)
        self.assertEqual(widget.checked_values(), {"Самара", "Тольятти"})
        widget._set_all(False)
        self.assertEqual(widget.checked_values(), set())


    def test_search_field_filters_visible_checkboxes_only(self):
        widget = CheckableDropdown("Категории")
        widget.set_items(["Кафе", "Кофейня", "Автосервис"])
        # QCheckBox.isVisible() is false while any parent widget is hidden.
        # Show the popup so this test checks the actual user-visible state.
        widget._popup.show()
        self.app.processEvents()
        widget._search_edit.setText("коф")
        self.app.processEvents()
        self.assertFalse(widget._items["Кафе"].isVisible())
        self.assertTrue(widget._items["Кофейня"].isVisible())
        self.assertFalse(widget._items["Автосервис"].isVisible())

    def test_category_list_is_scrollable_and_popup_is_screen_bounded(self):
        widget = CheckableDropdown("Категории")
        widget.set_items([f"Категория {i}" for i in range(500)])
        self.assertIsNotNone(widget._scroll)
        self.assertGreater(widget._scroll.maximumHeight(), 0)
        self.assertLessEqual(widget._popup.maximumHeight(), widget.screen().availableGeometry().height())

    def test_checkbox_changes_commit_only_when_popup_closes(self):
        widget = CheckableDropdown("Категории")
        widget.set_items(["Кафе", "Квесты"])
        commits = []
        widget.committed.connect(lambda: commits.append(True))
        widget._popup.show()
        self.app.processEvents()
        widget._items["Кафе"].setChecked(False)
        self.assertEqual(commits, [])
        widget._popup.hide()
        self.app.processEvents()
        self.assertEqual(commits, [True])

    def test_refresh_drops_stale_settlement_values(self):
        widget = CheckableDropdown("Населённый пункт")
        widget.set_items(["Самара", "Тольятти"])
        widget._set_all(True)
        widget.set_items(["Самара"], {"Самара", "Тольятти"})
        self.assertEqual(widget.checked_values(), {"Самара"})


if __name__ == "__main__":
    unittest.main()

@unittest.skipIf(QApplication is None, "PyQt6 is not installed in the audit environment")
class ColumnVisibilityPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_columns_are_visible_by_default(self):
        from yabiztracker.ui.widgets import ColumnVisibilityPopup
        popup = ColumnVisibilityPopup(["Название", "E-mail", "Сайт"])
        self.assertEqual(len(popup._checkboxes), 3)
        self.assertTrue(all(popup.is_column_visible(c) for c in range(3)))

    def test_checkbox_emits_visibility_change_and_stays_available(self):
        from yabiztracker.ui.widgets import ColumnVisibilityPopup
        popup = ColumnVisibilityPopup(["Название", "E-mail"])
        changes = []
        popup.visibility_changed.connect(lambda column, visible: changes.append((column, visible)))
        popup.show()
        self.app.processEvents()
        popup.checkbox(1).setChecked(False)
        self.assertFalse(popup.is_column_visible(1))
        self.assertEqual(changes, [])
        popup.hide()
        self.app.processEvents()
        self.assertEqual(changes, [(1, False)])
        self.assertTrue(popup.checkbox(0).isChecked())

    def test_popup_uses_popup_window_flag_for_outside_click_close_behavior(self):
        from PyQt6.QtCore import Qt
        from yabiztracker.ui.widgets import ColumnVisibilityPopup
        popup = ColumnVisibilityPopup(["Название"])
        self.assertTrue(bool(popup.windowFlags() & Qt.WindowType.Popup))

@unittest.skipIf(QApplication is None, "PyQt6 is not installed in the audit environment")
class OrganizationSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _table(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt
        from yabiztracker.ui.widgets import OrganizationTableWidget
        table = OrganizationTableWidget(5, 2)
        for row in range(5):
            item = QTableWidgetItem(f"Org {row}")
            item.setData(Qt.ItemDataRole.UserRole, f"id-{row}")
            table.setItem(row, 0, item)
            table.setItem(row, 1, QTableWidgetItem(str(row)))
        table.show()
        self.app.processEvents()
        return table

    def test_shift_range_keeps_lower_anchor_when_selecting_upward(self):
        table = self._table()
        table._selection_anchor_row = 4
        table._selection_anchor_key = table._row_key(4)
        table.select_visible_range(4, 1)
        self.assertEqual([i.row() for i in table.selectionModel().selectedRows()], [1, 2, 3, 4])
        self.assertEqual(table._find_anchor_row(), 4)

    def test_shift_range_does_not_call_selection_model_index(self):
        table = self._table()
        table._selection_anchor_row = 3
        table._selection_anchor_key = table._row_key(3)
        table.select_visible_range(3, 0)
        self.assertEqual([i.row() for i in table.selectionModel().selectedRows()], [0, 1, 2, 3])

    def test_shift_range_keeps_lower_anchor_selected_after_event_loop_turn(self):
        table = self._table()
        table._selection_anchor_row = 4
        table._selection_anchor_key = table._row_key(4)
        table.select_visible_range(4, 1)
        self.assertIn(4, [i.row() for i in table.selectionModel().selectedRows()])
        self.app.processEvents()
        selected = [i.row() for i in table.selectionModel().selectedRows()]
        self.assertEqual(selected, [1, 2, 3, 4])
        self.assertEqual(table._find_anchor_row(), 4)

    def test_shift_range_excludes_hidden_rows(self):
        table = self._table()
        table.setRowHidden(2, True)
        table._selection_anchor_row = 4
        table._selection_anchor_key = table._row_key(4)
        table.select_visible_range(4, 0)
        self.assertEqual([i.row() for i in table.selectionModel().selectedRows()], [0, 1, 3, 4])
        self.assertNotIn(2, [i.row() for i in table.selectionModel().selectedRows()])
