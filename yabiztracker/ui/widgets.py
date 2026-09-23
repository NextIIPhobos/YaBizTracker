from __future__ import annotations

from PyQt6.QtCore import QItemSelectionModel, QTimer, Qt, pyqtSignal
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
    """Responsive multi-select popup with searchable checkbox list.

    The popup is shared by large faceted filters such as settlements and
    categories.  All values are checked when the list is initialized without
    an explicit selection.  A later ``set_items`` call preserves the supplied
    selection and silently drops values that no longer exist.
    """

    changed = pyqtSignal()

    def __init__(self, title="Выбор", parent=None):
        super().__init__(parent)
        self._items: dict[str, QCheckBox] = {}
        self._title = title
        self._popup = None
        self._search_edit = None
        self._list_widget = None
        self._scroll = None
        self._values: list[str] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton(title)
        self.button.setMinimumWidth(180)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.clicked.connect(self._toggle_popup)
        layout.addWidget(self.button)

    def set_items(self, values, checked=None):
        normalized = []
        seen = set()
        for value in values:
            text = str(value).strip()
            key = text.casefold()
            if text and key not in seen:
                normalized.append(text)
                seen.add(key)
        normalized.sort(key=str.casefold)
        was_all_selected = bool(self._items) and len(self.checked_values()) == len(self._items)
        previous = {str(v).strip() for v in (checked or [])}
        initial = checked is None or was_all_selected
        selected_keys = {v.casefold() for v in previous}

        self._items.clear()
        self._values = normalized
        if self._popup is not None:
            self._popup.deleteLater()
            self._popup = None

        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setFrameShape(QFrame.Shape.StyledPanel)
        popup.setMinimumWidth(max(260, self.width(), 320 if len(normalized) > 30 else 0))
        popup.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        outer = QVBoxLayout(popup)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(5)

        search = QLineEdit()
        search.setPlaceholderText(f"Поиск {self._title.lower()}…")
        search.setClearButtonEnabled(True)
        search.setMinimumHeight(30)
        outer.addWidget(search)
        self._search_edit = search

        actions = QHBoxLayout()
        all_btn = QPushButton("Выбрать все")
        none_btn = QPushButton("Снять все")
        actions.addWidget(all_btn)
        actions.addWidget(none_btn)
        outer.addLayout(actions)

        list_box = QWidget()
        list_layout = QVBoxLayout(list_box)
        list_layout.setContentsMargins(2, 0, 2, 0)
        list_layout.setSpacing(2)
        self._list_widget = list_box

        for text in normalized:
            cb = QCheckBox(text)
            cb.setChecked(initial or text.casefold() in selected_keys)
            cb.stateChanged.connect(self._on_state_changed)
            self._items[text] = cb
            list_layout.addWidget(cb)

        empty = QLabel("Нет доступных значений")
        empty.setEnabled(False)
        list_layout.addWidget(empty)
        empty.setVisible(not self._items)
        self._empty_label = empty

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(list_box)
        self._scroll = scroll
        outer.addWidget(scroll, 1)

        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn.clicked.connect(lambda: self._set_all(False))
        search.textChanged.connect(self._filter_items)

        self._popup = popup
        self._update_button()
        self._resize_popup_to_screen()

    def _filter_items(self, text):
        query = str(text or "").strip().casefold()
        visible = 0
        for value, cb in self._items.items():
            show = not query or query in value.casefold()
            cb.setVisible(show)
            if show:
                visible += 1
        self._empty_label.setVisible(visible == 0)
        self._resize_popup_to_screen()

    def _resize_popup_to_screen(self):
        if self._popup is None:
            return
        screen = self.screen()
        available = screen.availableGeometry() if screen else None
        if available:
            max_height = max(220, int(available.height() * 0.72))
            self._scroll.setMaximumHeight(max_height - 105)
            self._popup.setMaximumHeight(max_height)
            self._popup.setMaximumWidth(min(520, max(320, int(available.width() * 0.42))))
        self._popup.adjustSize()

    def _toggle_popup(self):
        if self._popup is None:
            return
        self._resize_popup_to_screen()
        pos = self.mapToGlobal(self.rect().bottomLeft())
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            x = min(pos.x(), available.right() - self._popup.width())
            y = min(pos.y(), available.bottom() - self._popup.height())
            if y < available.top():
                y = max(available.top(), self.mapToGlobal(self.rect().topLeft()).y() - self._popup.height())
            pos.setX(max(available.left(), x))
            pos.setY(max(available.top(), y))
        self._popup.move(pos)
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()
        self._search_edit.setFocus()

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
        if not self._items:
            text = self._title
        elif len(selected) == len(self._items):
            text = f"{self._title}: все"
        elif not selected:
            text = f"{self._title}: ничего"
        else:
            text = f"{self._title}: {len(selected)}"
        self.button.setText(text)

    def checked_values(self):
        return {value for value, cb in self._items.items() if cb.isChecked()}

    def close_popup(self):
        if self._popup is not None:
            self._popup.hide()


class ColumnVisibilityPopup(QFrame):
    """Popup containing one checkbox per table column.

    ``QFrame.Popup`` gives the desired interaction contract: the popup remains
    open while the user toggles checkboxes and closes automatically when the
    user clicks outside its bounds.
    """

    visibility_changed = pyqtSignal(int, bool)

    def __init__(self, headers, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("columnVisibilityPopup")
        self.setMinimumWidth(280)
        self._checkboxes: dict[int, QCheckBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(5)
        title = QLabel("Отображаемые столбцы")
        title.setStyleSheet("font-weight: 600;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(430)
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(2)

        for column, header in enumerate(headers):
            checkbox = QCheckBox(str(header))
            checkbox.setChecked(True)
            checkbox.toggled.connect(lambda checked, c=column: self.visibility_changed.emit(c, checked))
            self._checkboxes[column] = checkbox
            list_layout.addWidget(checkbox)

        scroll.setWidget(list_widget)
        outer.addWidget(scroll)

    def checkbox(self, column: int):
        return self._checkboxes[column]

    def is_column_visible(self, column: int) -> bool:
        return self._checkboxes[column].isChecked()


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
        # Keep the anchor identity before touching Qt's selection model.
        # QTableWidget can internally reconcile the current index after a
        # selection change; on Windows that may drop the
        # original anchor when the range is selected upward. The anchor is
        # therefore restored explicitly both synchronously and on the next
        # event-loop turn.
        anchor_key = self._selection_anchor_key
        self._pruning_selection = True
        try:
            if not extend:
                model.clearSelection()
            flags = (QItemSelectionModel.SelectionFlag.Select |
                     QItemSelectionModel.SelectionFlag.Rows)
            for row in selected_rows:
                model.select(self.model().index(row, 0), flags)

            resolved_anchor = self._find_anchor_row()
            if resolved_anchor is not None and resolved_anchor in selected_rows:
                model.select(self.model().index(resolved_anchor, 0), flags)

            self.setCurrentCell(target_row, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        finally:
            self._pruning_selection = False
        self.prune_hidden_selection()

        # A second pass is intentional: QTableWidget may emit/update its
        # selection state after this method returns from mousePressEvent.
        # Re-apply only the anchor, never the whole range, so the user's
        # existing selection semantics remain untouched.
        if anchor_key is not None:
            QTimer.singleShot(0, lambda key=anchor_key: self._restore_selection_anchor(key))

    def _restore_selection_anchor(self, anchor_key):
        if anchor_key is None or not self.selectionModel():
            return
        anchor_row = None
        for row in range(self.rowCount()):
            if self.isRowHidden(row):
                continue
            if self._row_key(row) == anchor_key:
                anchor_row = row
                break
        if anchor_row is None:
            return
        flags = (QItemSelectionModel.SelectionFlag.Select |
                 QItemSelectionModel.SelectionFlag.Rows)
        self._pruning_selection = True
        try:
            self.selectionModel().select(self.model().index(anchor_row, 0), flags)
        finally:
            self._pruning_selection = False

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
