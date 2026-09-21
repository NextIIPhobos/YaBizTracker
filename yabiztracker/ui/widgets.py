from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QItemSelectionModel
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QLabel, QPushButton, QSizePolicy,
    QTableWidget, QFrame, QVBoxLayout, QCheckBox, QScrollArea,
)

from ..domain.selection import visible_range




class PresenceFilterButton(QPushButton):
    """Three-state presence filter: all -> has value -> has no value -> all."""

    MODES = ("all", "has", "missing")

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._mode = "all"
        self.clicked.connect(self._cycle_mode)
        self._update_tooltip()

    @property
    def mode(self):
        return self._mode

    def _cycle_mode(self):
        self._mode = self.MODES[(self.MODES.index(self._mode) + 1) % len(self.MODES)]
        self._update_tooltip()
        self.setProperty("presenceMode", self._mode)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _update_tooltip(self):
        text = {
            "all": "Все организации",
            "has": "Есть значение — нажмите ещё раз, чтобы показать организации без значения",
            "missing": "Нет значения — нажмите ещё раз, чтобы отключить фильтр",
        }[self._mode]
        self.setToolTip(text)
        self.setStyleSheet({
            "all": "",
            "has": "QPushButton { font-weight: 600; }",
            "missing": "QPushButton { font-weight: 600; text-decoration: underline; }",
        }[self._mode])


class CheckableDropdown(QWidget):
    """Compact multi-select dropdown with a real checkbox list.

    The widget keeps its state as a set of values and exposes a single
    ``changed`` signal. It is intentionally independent of the organization
    table, so it can be reused for other faceted filters later.
    """

    changed = pyqtSignal()

    def __init__(self, title="Выбор", parent=None):
        super().__init__(parent)
        self._items: dict[str, QCheckBox] = {}
        self._title = title
        self._popup = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton(title)
        self.button.setMinimumWidth(180)
        self.button.clicked.connect(self._toggle_popup)
        layout.addWidget(self.button)

    def set_items(self, values, checked=None):
        checked = {str(v) for v in (checked or [])}
        self._items.clear()
        if self._popup is not None:
            self._popup.deleteLater()
            self._popup = None

        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setFrameShape(QFrame.Shape.StyledPanel)
        popup.setMinimumWidth(max(220, self.width()))
        outer = QVBoxLayout(popup)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        actions = QHBoxLayout()
        all_btn = QPushButton("Выбрать все")
        none_btn = QPushButton("Сбросить")
        actions.addWidget(all_btn)
        actions.addWidget(none_btn)
        outer.addLayout(actions)

        list_box = QWidget()
        list_layout = QVBoxLayout(list_box)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(2)

        for value in values:
            text = str(value).strip()
            if not text or text in self._items:
                continue
            cb = QCheckBox(text)
            cb.setChecked(text in checked)
            cb.stateChanged.connect(self._on_state_changed)
            self._items[text] = cb
            list_layout.addWidget(cb)

        if not self._items:
            empty = QLabel("Нет настроенных населённых пунктов")
            empty.setEnabled(False)
            list_layout.addWidget(empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(300)
        scroll.setWidget(list_box)
        outer.addWidget(scroll)
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn.clicked.connect(lambda: self._set_all(False))
        self._popup = popup
        self._update_button()

    def _toggle_popup(self):
        if self._popup is None:
            return
        self._popup.adjustSize()
        pos = self.mapToGlobal(self.rect().bottomLeft())
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            x = min(pos.x(), available.right() - self._popup.width())
            y = min(pos.y(), available.bottom() - self._popup.height())
            pos.setX(max(available.left(), x))
            pos.setY(max(available.top(), y))
        self._popup.move(pos)
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()

    def _set_all(self, checked):
        for cb in self._items.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self._update_button()
        self.changed.emit()

    def _on_state_changed(self, _state):
        self._update_button()
        self.changed.emit()

    def _update_button(self):
        selected = self.checked_values()
        if not selected:
            text = self._title
        elif len(selected) == len(self._items):
            text = f"{self._title}: все"
        else:
            text = f"{self._title}: {len(selected)}"
        self.button.setText(text)

    def checked_values(self):
        return {value for value, cb in self._items.items() if cb.isChecked()}

    def close_popup(self):
        if self._popup is not None:
            self._popup.hide()



class CityRow(QWidget):
    changed=pyqtSignal(object)
    remove_requested=pyqtSignal(object)
    def __init__(self,data=None):
        super().__init__();self.data=data;self._internal=False
        layout=QHBoxLayout(self);layout.setContentsMargins(0,2,0,2)
        self.edit=QLineEdit();self.edit.setPlaceholderText("Город, посёлок или село…");self.edit.setMinimumHeight(30);self.edit.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);layout.addWidget(self.edit,1)
        self.status=QLabel("Не выбран");self.status.setMinimumWidth(210);layout.addWidget(self.status)
        self.remove=QPushButton("✕");self.remove.setFixedWidth(32);self.remove.clicked.connect(lambda:self.remove_requested.emit(self))
        layout.addWidget(self.remove)
        # Set the initial text without triggering _changed(): an existing
        # resolved city must remain selected when the settings dialog opens.
        self.edit.blockSignals(True)
        if data:
            self.edit.setText(data.get("name", ""))
            self.status.setText("✓ " + data.get("description", "населённый пункт"))
        self.edit.blockSignals(False)
        self.edit.textChanged.connect(self._changed)

    def _changed(self,text):
        # Programmatic selection of a suggestion must not look like a new user
        # edit. Otherwise textChanged starts the suggestion timer again and the
        # popup reappears shortly after the first selection.
        if self._internal:
            return
        self.data=None
        self.status.setText("⚠ Выберите вариант")
        self.changed.emit(self)

    def set_data(self,data):
        self._internal=True
        try:
            self.data=data or None
            self.edit.blockSignals(True)
            self.edit.setText((data or {}).get("name",""))
            self.edit.blockSignals(False)
            self.status.setText(("✓ "+data.get("description","")) if data else "⚠ Не выбран")
        finally:
            self.edit.blockSignals(False)
            self._internal=False

class OrganizationTableWidget(QTableWidget):
    """Organization grid with reliable Windows/Qt Shift-range selection.

    Qt's native ExtendedSelection is deliberately kept for ordinary Ctrl/Shift
    interaction, while Shift handling is made explicit so hidden rows created by
    the table's filter can never enter the selected set. The anchor is stored by
    row identity rather than a fragile visual row number, so sorting/filtering
    between clicks does not break the next Shift-click.
    """

    delete_requested = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pruning_selection = False
        self._manual_shift_click = False
        self._selection_anchor_key = None
        self._selection_anchor_row = None
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

    def _row_key(self, row: int):
        item = self.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value not in (None, "") else f"row:{row}"

    def _find_anchor_row(self):
        if self._selection_anchor_key is not None:
            for row in range(self.rowCount()):
                if self.isRowHidden(row):
                    continue
                if self._row_key(row) == self._selection_anchor_key:
                    return row
        row = self._selection_anchor_row
        if row is not None and 0 <= row < self.rowCount() and not self.isRowHidden(row):
            return row
        return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and not event.isAutoRepeat():
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        index = self.indexAt(event.position().toPoint())
        if not index.isValid() or self.isRowHidden(index.row()):
            super().mousePressEvent(event)
            return

        modifiers = event.modifiers()
        is_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        is_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        if is_shift:
            self._manual_shift_click = True
            anchor = self._find_anchor_row()
            if anchor is None:
                anchor = index.row()
                self._selection_anchor_row = anchor
                self._selection_anchor_key = self._row_key(anchor)

            self.select_visible_range(anchor, index.row(), extend=is_ctrl)
            # Keep Qt's current index in sync without invoking its mouse
            # selection algorithm a second time.
            self.setCurrentIndex(index)
            event.accept()
            return

        # For a normal click let Qt perform its native ExtendedSelection logic
        # first; the clicked row becomes the future Shift anchor. Ctrl-click is
        # intentionally also an anchor, matching common desktop table UX.
        self._selection_anchor_row = index.row()
        self._selection_anchor_key = self._row_key(index.row())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Our Shift selection is fully applied during mousePressEvent. Qt's
        # release handler must not run a second selection operation afterwards.
        if event.button() == Qt.MouseButton.LeftButton and self._manual_shift_click:
            self._manual_shift_click = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        self.prune_hidden_selection()

    def visible_selected_rows(self):
        if not self.selectionModel():
            return []
        return [index for index in self.selectionModel().selectedRows()
                if not self.isRowHidden(index.row())]

    def prune_hidden_selection(self):
        if self._pruning_selection or not self.selectionModel():
            return
        hidden_rows = [index.row() for index in self.selectionModel().selectedRows()
                       if self.isRowHidden(index.row())]
        if not hidden_rows:
            return
        self._pruning_selection = True
        try:
            flags = (QItemSelectionModel.SelectionFlag.Deselect |
                     QItemSelectionModel.SelectionFlag.Rows)
            for row in hidden_rows:
                self.selectionModel().select(self.model().index(row, 0), flags)
        finally:
            self._pruning_selection = False

    def select_visible_range(self, anchor_row: int, target_row: int, *, extend: bool = False):
        """Select the inclusive visible range, never hidden rows.

        Selection is applied one row at a time. This is slightly more explicit
        than constructing QItemSelection ranges, but avoids Qt treating a range
        spanning hidden rows as a contiguous model range and is deterministic
        with QTableWidget on Windows.
        """
        visible_rows = [row for row in range(self.rowCount()) if not self.isRowHidden(row)]
        selected_rows = visible_range(visible_rows, anchor_row, target_row)
        if not selected_rows:
            return

        model = self.selectionModel()
        self._pruning_selection = True
        try:
            if not extend:
                model.clearSelection()
            flags = (QItemSelectionModel.SelectionFlag.Select |
                     QItemSelectionModel.SelectionFlag.Rows)
            for row in selected_rows:
                model.select(model.index(row, 0), flags)
            self.setCurrentCell(target_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        finally:
            self._pruning_selection = False
        self.prune_hidden_selection()

    def select_visible_rows(self):
        if not self.selectionModel():
            return
        visible_rows = [row for row in range(self.rowCount()) if not self.isRowHidden(row)]
        self._pruning_selection = True
        try:
            self.selectionModel().clearSelection()
            flags = (QItemSelectionModel.SelectionFlag.Select |
                     QItemSelectionModel.SelectionFlag.Rows)
            for row in visible_rows:
                self.selectionModel().select(self.model().index(row, 0), flags)
        finally:
            self._pruning_selection = False
        self.prune_hidden_selection()
