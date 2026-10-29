"""Closed-but-active trips must be visible even without scheduled reminders."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QVBoxLayout, QWidget, QMessageBox, QDialog,
)
from ui_tracking import DateTimeDialog
from tracking import display_datetime


class ActiveTripsPanel(QWidget):
    def __init__(self, db, on_changed, parent=None):
        super().__init__(parent)
        self.db = db
        self.on_changed = on_changed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Активные перевозки")
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Рейс", "Этап", "Загрузка / действие"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(120)
        self.table.setMaximumHeight(240)
        self.table.itemDoubleClicked.connect(lambda *_: self.choose_load_time())
        layout.addWidget(self.table)
        self.choose = QPushButton("Указать / изменить время загрузки выбранного рейса")
        self.choose.clicked.connect(self.choose_load_time)
        layout.addWidget(self.choose)

    def refresh(self):
        active = [x for x in self.db.routes(include_closed=True)
                  if x["status"] == "Закрыт"]
        self.table.setRowCount(len(active))
        missing = 0
        for index, route in enumerate(active):
            tracking = self.db.tracking(route["id"]) or {}
            if tracking.get("phase") in ("Завершён", "Пауза"):
                phase = tracking.get("phase") or "Закрыт"
            else:
                phase = tracking.get("phase") or "Нужно уточнить этап"
            due = tracking.get("load_due_at") or ""
            if not due and phase == "К загрузке":
                missing += 1
            details = (display_datetime(due) if due
                       else "Уточнить дату и время загрузки" if phase == "К загрузке"
                       else "Время не указано")
            for column, value in enumerate((f"{route['id']} · {route.get('origin') or '?'} → {route.get('destination') or '?'}",
                                             phase, details)):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, route["id"])
                if not due and column == 2 and phase == "К загрузке":
                    item.setForeground(Qt.GlobalColor.yellow)
                self.table.setItem(index, column, item)
        self.title.setText(f"Активные перевозки · {len(active)}"
                           + (f" · уточнить загрузку: {missing}" if missing else ""))
        self.choose.setEnabled(bool(active))

    def choose_load_time(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Выбери рейс", "Выдели строку рейса.")
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        route_id = item.data(Qt.ItemDataRole.UserRole)
        tracking = self.db.tracking(route_id) or {}
        if tracking.get("phase") != "К загрузке":
            QMessageBox.information(self, "Этап перевозки",
                                    "Изменить время можно на этапе «К загрузке».")
            return
        dialog = DateTimeDialog(
            "Время загрузки", "Укажи подтверждённые дату и время загрузки:",
            tracking.get("load_due_at"), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.db.delay_loading(route_id, dialog.value())
            self.on_changed()
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка сохранения", str(exc))
