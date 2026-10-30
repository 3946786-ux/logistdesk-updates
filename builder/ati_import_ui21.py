"""Manual ATI.SU clipboard import preview (no account/API connection)."""
from __future__ import annotations

from dataclasses import replace
import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
)
from ati_import21 import AtiImportLedger, parse_ati_text

HEADERS = ["Выбрать", "№ ATI", "Откуда", "Куда", "Вес", "Объём", "Дата загрузки", "Ставка ₽", "Кузов", "Загрузка", "ADR класс", "UN", "Проверка"]
EDITABLE = {2: "origin", 3: "destination", 4: "weight", 5: "volume", 6: "date_window", 7: "rate_rub", 8: "body", 9: "loading", 10: "adr_class", 11: "un_number"}


class AtiImportDialog(QDialog):
    """Only the user-confirmed, non-duplicate rows can be saved."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.ledger = AtiImportLedger(db)
        self.loads = []
        self.created_count = 0
        self.setWindowTitle("Импорт из ATI — предварительный просмотр")
        self.resize(1190, 760)
        layout = QVBoxLayout(self)
        intro = QLabel("Открой конкретный груз ATI, выдели описание вместе с номером, "
                       "нажми Ctrl+C и вставь Ctrl+V. Можно вставить и несколько грузов, "
                       "но для одного удобнее. Подключения к ATI нет.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.paste = QTextEdit(self)
        self.paste.setPlaceholderText("Вставь описание одного груза ATI вместе с его номером…")
        self.paste.setMaximumHeight(175)
        layout.addWidget(self.paste)
        detect = QPushButton("Распознать груз")
        detect.clicked.connect(self.preview)
        layout.addWidget(detect)
        self.summary = QLabel("Вставь текст груза и нажми «Распознать груз»")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(HEADERS), self)
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        hint = QLabel("Проверь все поля и поставь галочки только у нужных грузов. "
                      "Неуверенно распознанные значения можно исправить прямо в таблице. "
                      "Повторно импортированные номера ATI будут пропущены.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        actions.rejected.connect(self.reject)
        self.create_button = actions.addButton("Создать рейс", QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.clicked.connect(self.commit_selected)
        layout.addWidget(actions)

    def _cell(self, row, col, value, *, editable=False):
        item = QTableWidgetItem(str(value if value is not None else ""))
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, col, item)
        return item

    def preview(self):
        try:
            self.loads = parse_ati_text(self.paste.toPlainText())
            existing = self.ledger.existing(load.ati_id for load in self.loads)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Не удалось прочитать страницу", str(exc))
            return
        self.table.setRowCount(len(self.loads))
        for row, load in enumerate(self.loads):
            duplicate = load.ati_id in existing
            tick = self._cell(row, 0, "", editable=False)
            tick.setFlags(tick.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            tick.setCheckState(
                Qt.CheckState.Checked if len(self.loads) == 1 and not duplicate
                else Qt.CheckState.Unchecked
            )
            if duplicate:
                tick.setFlags(tick.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._cell(row, 1, load.ati_id)
            vals = [load.origin, load.destination, load.weight, load.volume, load.date_window,
                    load.rate_rub if load.rate_rub is not None else "", load.body, load.loading,
                    load.adr_class, load.un_number]
            for col, value in enumerate(vals, 2):
                self._cell(row, col, value, editable=True)
            status = ("Уже в рейсе " + existing[load.ati_id]) if duplicate else (
                "; ".join(load.warnings) if load.warnings else "Данные распознаны — проверь")
            self._cell(row, 12, status)
        self.table.resizeColumnsToContents()
        self.create_button.setText("Создать рейс" if len(self.loads) <= 1 else "Создать выбранные рейсы")
        self.summary.setText(f"Найдено грузов: {len(self.loads)}. "
                             f"Ранее импортировано: {len(existing)}. "
                             "При одном новом грузе он уже отмечен; проверь данные и подтверди.")
        if not self.loads:
            QMessageBox.information(self, "Грузы не найдены", "Номера грузов ATI не обнаружены. "
                                    "Дома проверим настоящий формат скопированного текста.")

    def commit_selected(self):
        selected = []
        for row, load in enumerate(self.loads):
            tick = self.table.item(row, 0)
            if tick is None or tick.checkState() != Qt.CheckState.Checked:
                continue
            fields = {}
            for col, name in EDITABLE.items():
                fields[name] = (self.table.item(row, col).text() or "").strip()
            if not fields["origin"] or not fields["destination"]:
                QMessageBox.warning(self, "Неполный маршрут", f"№ {load.ati_id}: заполни города.")
                return
            rate = fields.pop("rate_rub").replace(" ", "")
            if rate and (not rate.isdigit() or int(rate) <= 0):
                QMessageBox.warning(self, "Проверь ставку", f"№ {load.ati_id}: введи сумму в рублях цифрами.")
                return
            fields["rate_rub"] = int(rate) if rate else None
            if fields["adr_class"] and not re.fullmatch(r"[1-9](?:\.\d{1,2})?", fields["adr_class"]):
                QMessageBox.warning(self, "Проверь ADR", f"№ {load.ati_id}: укажи класс ADR цифрами.")
                return
            if fields["un_number"] and not re.fullmatch(r"\d{4}", fields["un_number"]):
                QMessageBox.warning(self, "Проверь UN", f"№ {load.ati_id}: номер ООН должен содержать 4 цифры.")
                return
            selected.append(replace(load, **fields))
        if not selected:
            QMessageBox.information(self, "Ничего не выбрано", "Отметь галочками нужные грузы.")
            return
        confirm = QMessageBox.question(
            self, "Создать рейсы?",
            f"Создать {len(selected)} выбранных рейсов? Существующие рейсы не перезаписываются. "
            "ADR и UN обязательно сверь с данными о грузе. Неизвестные поля останутся пустыми.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        done, duplicates = 0, 0
        try:
            for load in selected:
                _, created = self.ledger.import_load(load)
                done += int(created)
                duplicates += int(not created)
        except Exception as exc:
            self.created_count += done
            QMessageBox.critical(self, "Не все рейсы импортированы",
                                 f"Создано: {done}. Пропущено повторов: {duplicates}. Ошибка: {exc}. "
                                 "Уже созданные рейсы сохранены; проверь список рейсов перед повтором.")
            return
        self.created_count += done
        QMessageBox.information(self, "Импорт завершён", f"Новых рейсов: {done}. Повторов: {duplicates}.")
        self.accept()
