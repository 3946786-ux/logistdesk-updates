"""Small, focused dialogs for closing routes and adjusting transport ETA."""
from __future__ import annotations
import os
from pathlib import Path
from PySide6.QtCore import QDate, QDateTime, QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)
from rules import money
from ui_common import style_combo_popup, RussianMessageBox as QMessageBox
from tracking import iso_minute, parse_local_datetime
from input_formatting import bind_phone
import autostart


def date_time_editor(value: str | None = None) -> QDateTimeEdit:
    editor = QDateTimeEdit()
    editor.setDisplayFormat("dd.MM.yy HH:mm")
    editor.setCalendarPopup(True)
    editor.setDateTime(QDateTime(QDate.currentDate().addDays(1), QTime(10, 0)))
    if value:
        try:
            parsed = parse_local_datetime(value)
            editor.setDateTime(QDateTime(QDate(parsed.year, parsed.month, parsed.day),
                                         QTime(parsed.hour, parsed.minute)))
        except ValueError:
            pass
    return editor


class DateTimeDialog(QDialog):
    def __init__(self, title: str, caption: str, initial: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(410)
        layout = QVBoxLayout(self)
        tip = QLabel(caption)
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.editor = date_time_editor(initial)
        layout.addWidget(self.editor)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить время")
        controls.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def value(self) -> str:
        return self.editor.dateTime().toString("yyyy-MM-ddTHH:mm")


class CloseRouteDialog(QDialog):
    def __init__(self, route: dict, carriers: list[dict], preferred_id: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Закрыть рейс и включить контроль")
        self.setMinimumWidth(535)
        self.carriers = {c["id"]: c for c in carriers}
        layout = QVBoxLayout(self)
        title = QLabel(f"{route['id']} · {route.get('origin') or '?'} → {route.get('destination') or '?'}")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(13)
        self.carrier = QComboBox()
        for c in carriers:
            description = (f"{c.get('carrier') or 'Без имени'} · {c.get('phone') or 'без телефона'} "
                           f"· {c.get('body') or 'машина не указана'} · {money(c.get('desired_rate')) or 'без ставки'}")
            self.carrier.addItem(description, c["id"])
        style_combo_popup(self.carrier)
        if preferred_id:
            idx = self.carrier.findData(preferred_id)
            if idx >= 0:
                self.carrier.setCurrentIndex(idx)
        form.addRow("Согласованная машина", self.carrier)
        self.driver_name = QLineEdit()
        self.driver_name.setPlaceholderText("Имя водителя, если известно")
        form.addRow("Имя водителя", self.driver_name)
        self.driver_phone = QLineEdit()
        self.driver_phone.setPlaceholderText("Телефон водителя (отдельно от перевозчика)")
        bind_phone(self.driver_phone)
        form.addRow("Номер водителя", self.driver_phone)
        # The date choice is visible on every close action; no hidden opt-in checkbox.
        self.use_load_time = QCheckBox()
        self.use_load_time.setChecked(False)
        self.use_load_time.hide()
        tip = QLabel("Когда загрузка? Выбери дату и время или нажми «Уточню позже».")
        tip.setWordWrap(True)
        tip.setObjectName("sectionTitle")
        form.addRow(tip)
        self.load_time = date_time_editor()
        self.load_time.setEnabled(True)
        self.load_time.dateTimeChanged.connect(lambda *_: self.use_load_time.setChecked(True))
        form.addRow("Дата и время загрузки", self.load_time)
        layout.addLayout(form)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("Закрыть с указанной датой")
        later = controls.addButton("Уточню позже", QDialogButtonBox.ButtonRole.ActionRole)
        later.clicked.connect(self.accept_without_date)
        controls.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        controls.accepted.connect(self.validate)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self.carrier.currentIndexChanged.connect(self.fill_carrier)
        self.fill_carrier()

    def fill_carrier(self, *_):
        record = self.carriers.get(self.carrier.currentData()) or {}
        self.driver_name.setText(record.get("driver_name") or "")
        self.driver_phone.setText(record.get("driver_phone") or "")

    def accept_without_date(self):
        if self.carrier.currentData() is None:
            QMessageBox.warning(self, "Нет машины", "Выбери согласованного перевозчика.")
            return
        self.use_load_time.setChecked(False)
        self.accept()

    def validate(self):
        if self.carrier.currentData() is None:
            QMessageBox.warning(self, "Нет машины", "Выбери согласованного перевозчика.")
            return
        if not self.use_load_time.isChecked():
            QMessageBox.information(
                self, "Когда загрузка?",
                "Выбери дату/время загрузки либо нажми «Уточню позже».")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "carrier_id": self.carrier.currentData(),
            "driver_name": self.driver_name.text().strip(),
            "driver_phone": self.driver_phone.text().strip(),
            "load_due_at": self.load_time.dateTime().toString("yyyy-MM-ddTHH:mm")
                           if self.use_load_time.isChecked() else "",
        }


class AutoStartDialog(QDialog):
    def __init__(self, project_dir: Path, parent=None):
        super().__init__(parent)
        self.project_dir = project_dir
        self.setWindowTitle("Настройки LogistDesk")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        self.checkbox = QCheckBox("Запускать LogistDesk вместе с Windows")
        self.checkbox.setChecked(autostart.is_enabled())
        self.checkbox.setEnabled(os.name == "nt")
        layout.addWidget(self.checkbox)
        if os.name != "nt":
            layout.addWidget(QLabel("Автозапуск доступен только в Windows."))
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        controls.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        controls.accepted.connect(self.save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def save(self):
        try:
            if os.name == "nt":
                autostart.set_enabled(self.checkbox.isChecked(), self.project_dir)
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Не удалось настроить автозапуск", str(exc))
            return
        self.accept()
