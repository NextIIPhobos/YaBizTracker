from __future__ import annotations

from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDateTimeEdit, QComboBox, QStyledItemDelegate, QTableWidgetItem

from ..domain.models import STATUS_OPTIONS


class NextContactItem(QTableWidgetItem):
    """Ячейка даты: сортируется по реальному времени, а не по строке dd.MM.yyyy."""
    def __lt__(self, other):
        left=str(self.data(Qt.ItemDataRole.UserRole+1) or "")
        right=str(other.data(Qt.ItemDataRole.UserRole+1) or "") if other else ""
        if left and right:
            return left < right
        if left and not right:return False
        if not left and right:return True
        return super().__lt__(other)

class NextContactDelegate(QStyledItemDelegate):
    """Редактор даты/времени для столбца «Следующий контакт»."""
    def createEditor(self, parent, option, index):
        edit=QDateTimeEdit(parent)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd.MM.yyyy HH:mm")
        raw=str(index.data(Qt.ItemDataRole.UserRole+1) or "").strip()
        if raw:
            try: edit.setDateTime(datetime.strptime(raw,"%Y-%m-%d %H:%M"))
            except ValueError: edit.setDateTime(datetime.now())
        else: edit.setDateTime(datetime.now())
        return edit

    def setEditorData(self, editor, index):
        raw=str(index.data(Qt.ItemDataRole.UserRole+1) or "").strip()
        if raw:
            try: editor.setDateTime(datetime.strptime(raw,"%Y-%m-%d %H:%M"))
            except ValueError: pass

    def setModelData(self, editor, model, index):
        value=editor.dateTime().toString("yyyy-MM-dd HH:mm")
        model.setData(index,value,Qt.ItemDataRole.UserRole+1)
        model.setData(index,editor.dateTime().toString("dd.MM.yyyy HH:mm"),Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

class StatusDelegate(QStyledItemDelegate):
    """Редактор статуса из единого фиксированного списка значений."""
    def createEditor(self,parent,option,index):
        edit=QComboBox(parent);edit.addItems(STATUS_OPTIONS);return edit
    def setEditorData(self,editor,index):
        value=str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        pos=editor.findText(value)
        editor.setCurrentIndex(pos if pos >= 0 else 0)
    def setModelData(self,editor,model,index):
        model.setData(index,editor.currentText(),Qt.ItemDataRole.EditRole)
    def updateEditorGeometry(self,editor,option,index):
        editor.setGeometry(option.rect)
