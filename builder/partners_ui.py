"""Страница справочника компаний, водителей и автомобилей.

Импорт через Ctrl+V работает без промежуточного файла. Все результаты OCR
проходят через редактируемую форму подтверждения до сохранения.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, QEvent, QTimer
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QInputDialog,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget, QToolButton, QMenu,
)
from document_extract import DOCUMENT_FIELDS, FIELD_LABELS, file_text, image_text, parse_text
from partner_registry import PARTNER_FIELDS, DRIVER_FIELDS, VEHICLE_FIELDS, PartnerRegistry
from call_bridge import import_legacy_calls
from portable_transfer import export_contacts, import_contacts
from folder_sync import FolderSync
from document_archive import DocumentArchive
from input_formatting import bind_date, bind_phone, bind_document, series_number


ROLE_NAMES = {"carrier": "Перевозчик", "customer": "Заказчик", "both": "Обе роли"}
KIND_NAMES = {"partner": "Карточка организации", "driver": "Паспорт / ВУ", "vehicle": "СТС"}
VISIBLE_PARTNER_FIELDS = ("name", "inn", "kpp", "phone", "email", "legal_address",
                          "bank", "bik", "account", "corr_account", "note")
VISIBLE_DRIVER_FIELDS = ("surname", "first_name", "patronymic", "phone",
                         "passport_combined", "license_number", "note")
VISIBLE_VEHICLE_FIELDS = ("plate", "brand", "trailer_brand", "trailer_plate",
                          "body_type", "payload_t", "volume_m3", "body_length_m",
                          "body_width_m", "body_height_m", "note")
VISIBLE_LABELS = {
    "passport_combined": "Серия и номер паспорта",
    "license_number": "Серия и номер ВУ",
    "trailer_brand": "Марка полуприцепа",
    "trailer_plate": "Госномер полуприцепа",
    "body_type": "Вид кузова",
    "payload_t": "Грузоподъёмность, т",
    "volume_m3": "Объём, м³",
    "body_length_m": "Длина кузова, м",
    "body_width_m": "Ширина кузова, м",
    "body_height_m": "Высота кузова, м",
    "short_name": "Краткое название", "actual_address": "Фактический адрес",
    "vat": "НДС", "payment_terms": "Условия оплаты", "note": "Заметка",
}


def editor_form(fields: tuple[str, ...], labels=None):
    widget = QWidget()
    layout = QFormLayout(widget)
    editors = {}
    for field in fields:
        if field == "partner_id" or field == "role":
            continue
        edit = QLineEdit()
        edit.setClearButtonEnabled(True)
        if field in ("passport_series", "passport_number", "license_number",
                     "registration_number"):
            edit.setMaxLength(40)
        editors[field] = edit
        layout.addRow(VISIBLE_LABELS.get(field, (labels or FIELD_LABELS).get(field, field)), edit)
        if field == "phone":
            bind_phone(edit)
        elif field.endswith("_date") or field == "birth_date":
            bind_date(edit)
        elif field in ("passport_combined", "license_number"):
            bind_document(edit)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    return scroll, editors


class DocumentReview(QDialog):
    def __init__(self, source_text: str, parent=None, source_available=False):
        super().__init__(parent)
        self.setWindowTitle("Проверка распознанных данных")
        self.resize(590, 680)
        self.source_text = source_text
        self.kind, _ = parse_text(source_text)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Проверь данные по оригиналу: распознавание может ошибаться."))
        kind_line = QHBoxLayout()
        kind_line.addWidget(QLabel("Тип документа:"))
        self.kind_select = QComboBox()
        for key, label in KIND_NAMES.items():
            self.kind_select.addItem(label, key)
        self.kind_select.setCurrentIndex(self.kind_select.findData(self.kind))
        kind_line.addWidget(self.kind_select, 1)
        layout.addLayout(kind_line)
        role_line = QHBoxLayout()
        self.role_label = QLabel("Добавить как:")
        role_line.addWidget(self.role_label)
        self.role_select = QComboBox(self)
        for role_key, title in ROLE_NAMES.items():
            self.role_select.addItem(title, role_key)
        role_line.addWidget(self.role_select, 1)
        layout.addLayout(role_line)
        self.container = QWidget()
        self.fields_layout = QFormLayout(self.container)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.container)
        layout.addWidget(scroll, 1)
        self.edits = {}
        self.kind_select.currentIndexChanged.connect(self.rebuild)
        self.rebuild()
        self.keep_source = QCheckBox("Сохранить оригинал документа в защищённой базе")
        self.keep_source.setChecked(False)
        self.keep_source.setVisible(source_available)
        layout.addWidget(self.keep_source)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Подтвердить и сохранить")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def rebuild(self):
        while self.fields_layout.count():
            item = self.fields_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.edits = {}
        self.kind = self.kind_select.currentData()
        self.role_label.setVisible(self.kind == "partner")
        self.role_select.setVisible(self.kind == "partner")
        _, extracted = parse_text(self.source_text, self.kind)
        for field in DOCUMENT_FIELDS[self.kind]:
            edit = QLineEdit(extracted.get(field, ""))
            edit.setClearButtonEnabled(True)
            self.fields_layout.addRow(FIELD_LABELS.get(field, field), edit)
            self.edits[field] = edit

    def values(self):
        return self.kind, {name: edit.text().strip()
                           for name, edit in self.edits.items() if edit.text().strip()}


class RegistryPage(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.registry = PartnerRegistry(db)
        self.partner_id = None
        self.driver_id = None
        self.vehicle_id = None
        self.setAcceptDrops(True)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("База перевозчиков и заказчиков"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: компания, ИНН, телефон…")
        self.search.textChanged.connect(self.reload_partners)
        left.addWidget(self.search)
        self.partner_list = QListWidget()
        self.partner_list.itemSelectionChanged.connect(self.on_partner_selected)
        left.addWidget(self.partner_list, 1)
        new_partner = QPushButton("Новая организация")
        new_partner.clicked.connect(self.new_partner)
        left.addWidget(new_partner)
        import_file = QPushButton("Добавить документы")
        import_file.setObjectName("primary")
        import_file.clicked.connect(self.attach_documents)
        left.addWidget(import_file)
        attachments = QPushButton("Мои документы")
        attachments.clicked.connect(self.show_originals)
        left.addWidget(attachments)
        paste = QPushButton("Вставить скрин (Ctrl+V)")
        paste.clicked.connect(self.paste_clipboard)
        left.addWidget(paste)
        advanced = QToolButton(self)
        advanced.setText("Ещё · импорт и обмен")
        advanced.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tools = QMenu(advanced)
        tools.addAction("Распознать документ", self.import_file)
        tools.addAction("Перенести старые звонки в базу", self.import_existing_calls)
        tools.addAction("Защищённый экспорт", self.export_contacts_file)
        tools.addAction("Импорт защищённой базы", self.import_contacts_file)
        self.sync_button = tools.addAction("Включить автообмен контактами", self.toggle_folder_sync)
        advanced.setMenu(tools)
        left.addWidget(advanced)
        self.folder_sync = None
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(120000)
        self.sync_timer.timeout.connect(self.run_folder_sync)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMinimumWidth(260)
        root.addWidget(left_widget, 1)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 2)
        self._make_partner_tab()
        self._make_child_tab("driver")
        self._make_child_tab("vehicle")
        self.reload_partners()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if (self.isVisible() and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_V
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and QApplication.clipboard().mimeData().hasImage()):
            self.paste_clipboard()
            return True
        return super().eventFilter(obj, event)

    def _make_partner_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Роль:"))
        self.role = QComboBox()
        for key, title in ROLE_NAMES.items():
            self.role.addItem(title, key)
        bar.addWidget(self.role, 1)
        save = QPushButton("Сохранить организацию")
        save.clicked.connect(self.save_partner)
        bar.addWidget(save)
        remove = QPushButton("Удалить")
        remove.setObjectName("danger")
        remove.clicked.connect(self.delete_selected_partner)
        bar.addWidget(remove)
        layout.addLayout(bar)
        form, self.partner_fields = editor_form(VISIBLE_PARTNER_FIELDS)
        layout.addWidget(form, 1)
        self.tabs.addTab(widget, "Организация")

    def _make_child_tab(self, kind):
        fields = VISIBLE_DRIVER_FIELDS if kind == "driver" else VISIBLE_VEHICLE_FIELDS
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        selector = QComboBox()
        selector.currentIndexChanged.connect(
            self.on_driver_selected if kind == "driver" else self.on_vehicle_selected)
        row.addWidget(selector, 1)
        add = QPushButton("Новый")
        add.clicked.connect(self.new_driver if kind == "driver" else self.new_vehicle)
        row.addWidget(add)
        save = QPushButton("Сохранить")
        save.clicked.connect(self.save_driver if kind == "driver" else self.save_vehicle)
        row.addWidget(save)
        delete = QPushButton("Удалить")
        delete.setObjectName("danger")
        delete.clicked.connect(
            self.delete_selected_driver if kind == "driver" else self.delete_selected_vehicle)
        row.addWidget(delete)
        layout.addLayout(row)
        # Drivers and vehicles are independent; no manual binding required.
        if kind == "driver":
            self.license_warning = QLabel("")
            self.license_warning.setWordWrap(True)
            self.license_warning.hide()  # Expiry warnings are not requested on the quick form.
        form, editors = editor_form(fields)
        layout.addWidget(form, 1)
        if kind == "driver":
            self.driver_select, self.driver_fields = selector, editors
        else:
            self.vehicle_select, self.vehicle_fields = selector, editors
        self.tabs.addTab(page, "Водители" if kind == "driver" else "Автомобили")

    def reload_partners(self, *_):
        previous = self.partner_id
        self.partner_list.blockSignals(True)
        self.partner_list.clear()
        for partner in self.registry.search(self.search.text()):
            name = partner["name"]
            if partner["inn"]:
                name += " · " + partner["inn"]
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, partner["id"])
            self.partner_list.addItem(item)
            if partner["id"] == previous:
                self.partner_list.setCurrentItem(item)
        self.partner_list.blockSignals(False)

    def on_partner_selected(self):
        item = self.partner_list.currentItem()
        if item is None:
            return
        partner = self.registry.get_partner(item.data(Qt.ItemDataRole.UserRole))
        if partner is None:
            return
        self.partner_id = partner["id"]
        self.role.setCurrentIndex(self.role.findData(partner["role"]))
        for field, editor in self.partner_fields.items():
            editor.setText(partner.get(field) or "")
        self.reload_children()

    def new_partner(self):
        self.partner_list.clearSelection()
        self.partner_list.setCurrentRow(-1)
        self.partner_id = None
        self.role.setCurrentIndex(0)
        for edit in self.partner_fields.values():
            edit.clear()
        self.reload_children()
        self.tabs.setCurrentIndex(0)

    def save_partner(self):
        record = self.registry.get_partner(self.partner_id) if self.partner_id is not None else {}
        record = dict(record or {})
        record.update({field: edit.text() for field, edit in self.partner_fields.items()})
        record["role"] = self.role.currentData()
        try:
            self.partner_id = self.registry.save_partner(record, self.partner_id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не сохранено", str(exc))
            return
        self.reload_partners()
        QMessageBox.information(self, "Сохранено", "Карточка организации сохранена.")

    def reload_children(self):
        self.driver_select.blockSignals(True)
        self.vehicle_select.blockSignals(True)
        self.driver_select.clear()
        self.vehicle_select.clear()
        self.driver_select.addItem("Новый водитель", None)
        self.vehicle_select.addItem("Новый автомобиль", None)
        if self.partner_id is not None:
            for item in self.registry.drivers(self.partner_id):
                title = " ".join(x for x in (
                    item["surname"], item["first_name"], item["patronymic"]) if x)
                self.driver_select.addItem(title or item["license_number"], item["id"])
            for item in self.registry.vehicles(self.partner_id):
                self.vehicle_select.addItem(
                    " · ".join(x for x in (item["plate"], item["brand"], item["model"]) if x),
                    item["id"])
        self.driver_select.blockSignals(False)
        self.vehicle_select.blockSignals(False)
        self.new_driver()
        self.new_vehicle()
        if self.partner_id is not None:
            expiring = [x for x in self.registry.expiring_licenses()
                        if x["partner_id"] == self.partner_id]
            if expiring:
                lines = []
                for item in expiring[:5]:
                    remaining = item["days_left"]
                    status = "истёк" if remaining < 0 else f"осталось {remaining} дн."
                    name = " ".join(x for x in (item["surname"], item["first_name"]) if x)
                    lines.append(f"{name}: ВУ {status}")
                self.license_warning.setText("ВНИМАНИЕ · сроки ВУ:\\n" + "\\n".join(lines))
            else:
                self.license_warning.setText("Сроки водительских удостоверений: без ближайших предупреждений")
        else:
            self.license_warning.setText("")

    def on_driver_selected(self):
        self.driver_id = self.driver_select.currentData()
        if not self.driver_id:
            self.new_driver(reset_selector=False)
            return
        item = next((x for x in self.registry.drivers(self.partner_id)
                     if x["id"] == self.driver_id), {})
        for field, edit in self.driver_fields.items():
            if field == "passport_combined":
                value = (str(item.get("passport_series") or "")
                         + " " + str(item.get("passport_number") or "")).strip()
                edit.setText(value)
            elif field == "license_number":
                edit.setText(series_number(item.get(field) or ""))
            else:
                edit.setText(item.get(field) or "")

    def on_vehicle_selected(self):
        self.vehicle_id = self.vehicle_select.currentData()
        if not self.vehicle_id:
            self.new_vehicle(reset_selector=False)
            return
        item = next((x for x in self.registry.vehicles(self.partner_id)
                     if x["id"] == self.vehicle_id), {})
        for field, edit in self.vehicle_fields.items():
            edit.setText(item.get(field) or "")

    def new_driver(self, reset_selector=True):
        self.driver_id = None
        if reset_selector:
            self.driver_select.setCurrentIndex(0)
        for edit in self.driver_fields.values():
            edit.clear()

    def new_vehicle(self, reset_selector=True):
        self.vehicle_id = None
        if reset_selector:
            self.vehicle_select.setCurrentIndex(0)
        for edit in self.vehicle_fields.values():
            edit.clear()

    def delete_selected_partner(self):
        if self.partner_id is None:
            return
        answer = QMessageBox.question(
            self, "Удалить организацию из справочника",
            "Будут удалены её контакты, водители, машины и приложенные документы. "
            "Сами рейсы и звонки сохранятся. Старые резервные копии останутся. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.registry.delete_partner(self.partner_id)
            self.new_partner()
            self.reload_partners()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не удалось удалить", str(exc))

    def delete_selected_driver(self):
        if self.driver_id is None:
            return
        if QMessageBox.question(
            self, "Удалить водителя", "Удалить карточку и приложенные оригиналы? "
            "Рейсы и звонки останутся; резервные копии сохраняются.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.registry.delete_driver(self.driver_id)
            self.reload_children()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не удалось удалить", str(exc))

    def delete_selected_vehicle(self):
        if self.vehicle_id is None:
            return
        if QMessageBox.question(
            self, "Удалить автомобиль", "Удалить карточку СТС и приложенные оригиналы?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.registry.delete_vehicle(self.vehicle_id)
            self.reload_children()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не удалось удалить", str(exc))

    def link_selected_driver_vehicle(self):
        if not self.driver_id or not self.vehicle_id:
            QMessageBox.information(
                self, "Выбор водителя и машины",
                "Сначала выбери существующего водителя во вкладке «Водители» "
                "и автомобиль во вкладке «Автомобили».")
            return
        try:
            self.registry.link_driver_vehicle(self.driver_id, self.vehicle_id)
            QMessageBox.information(self, "Готово", "Машина привязана к водителю.")
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось связать", str(exc))

    def save_driver(self):
        if self.partner_id is None:
            QMessageBox.warning(self, "Нет организации", "Сначала сохрани компанию-перевозчика.")
            return
        previous = next((x for x in self.registry.drivers(self.partner_id)
                         if x["id"] == self.driver_id), {})
        data = dict(previous)
        data.update({f: edit.text() for f, edit in self.driver_fields.items()
                     if f != "passport_combined"})
        passport = "".join(x for x in self.driver_fields["passport_combined"].text()
                           if x.isdigit())
        if passport and len(passport) != 10:
            QMessageBox.warning(self, "Проверь паспорт", "Укажи 4 цифры серии и 6 цифр номера.")
            return
        data["passport_series"] = passport[:4]
        data["passport_number"] = passport[4:]
        data["partner_id"] = self.partner_id
        try:
            identifier = self.registry.save_driver(data, self.driver_id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не сохранено", str(exc))
            return
        self.reload_children()
        self.driver_select.setCurrentIndex(self.driver_select.findData(identifier))

    def save_vehicle(self):
        if self.partner_id is None:
            QMessageBox.warning(self, "Нет организации", "Сначала сохрани компанию-перевозчика.")
            return
        previous = next((x for x in self.registry.vehicles(self.partner_id)
                         if x["id"] == self.vehicle_id), {})
        data = dict(previous)
        data.update({f: edit.text() for f, edit in self.vehicle_fields.items()})
        data["partner_id"] = self.partner_id
        if not data.get("volume_m3"):
            try:
                dimensions = [float(str(data[k]).replace(",", "."))
                              for k in ("body_length_m", "body_width_m", "body_height_m")]
                if all(x > 0 for x in dimensions):
                    data["volume_m3"] = str(round(
                        dimensions[0] * dimensions[1] * dimensions[2], 2))
            except (ValueError, TypeError, KeyError):
                pass
        try:
            identifier = self.registry.save_vehicle(data, self.vehicle_id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не сохранено", str(exc))
            return
        self.reload_children()
        self.vehicle_select.setCurrentIndex(self.vehicle_select.findData(identifier))

    def _review(self, text, *, original=None, filename=""):
        if not text.strip():
            QMessageBox.warning(self, "Нет текста", "Документ пуст или его не удалось распознать.")
            return
        dialog = DocumentReview(text, self, source_available=original is not None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        kind, fields = dialog.values()
        if not fields:
            QMessageBox.warning(self, "Нет реквизитов", "Не удалось определить поля. Проверь документ.")
            return
        if kind == "partner":
            if fields.get("inn"):
                match = self.registry.find_inn(fields["inn"])
            else:
                match = None
            if match:
                answer = QMessageBox.question(
                    self, "Контрагент уже существует",
                    "ИНН уже есть у «" + match["name"] + "». Дополнить его карточку?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                merged = {key: match.get(key) or "" for key in PARTNER_FIELDS}
                merged.update(fields)
                selected_role = dialog.role_select.currentData()
                if selected_role and selected_role != match["role"]:
                    merged["role"] = ("both" if match["role"] != "both" else match["role"])
                partner_id = match["id"]
            else:
                merged = dict(fields)
                merged["role"] = dialog.role_select.currentData()
                partner_id = None
            try:
                self.partner_id = self.registry.save_partner(merged, partner_id)
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Не сохранено", str(exc))
                return
            self._store_original(dialog, "partner", self.partner_id, original, filename)
            self.search.clear()
            self.reload_partners()
            for index in range(self.partner_list.count()):
                item = self.partner_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == self.partner_id:
                    self.partner_list.setCurrentItem(item)
                    break
            self.tabs.setCurrentIndex(0)
            return
        if self.partner_id is None:
            QMessageBox.warning(self, "Выбери перевозчика",
                                "Сначала выбери или создай организацию для этого документа.")
            return
        fields["partner_id"] = self.partner_id
        try:
            if kind == "driver":
                selected = self.driver_id
                target = next((d for d in self.registry.drivers(self.partner_id)
                               if d["id"] == selected), None)
                if target:
                    answer = QMessageBox.question(
                        self, "Водитель уже выбран",
                        "Дополнить выбранную карточку водителя?\\n"
                        "Да — объединить данные, Нет — отдельный водитель, "
                        "Отмена — ничего не менять.\\n"
                        "При совпадении поля новые значения будут предложены вместо старых.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                        QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
                    if answer == QMessageBox.StandardButton.Cancel:
                        return
                    if answer == QMessageBox.StandardButton.Yes:
                        merged = {key: target.get(key) or "" for key in DRIVER_FIELDS}
                        merged.update(fields)
                        fields = merged
                    else:
                        selected = None
                identifier = self.registry.save_driver(fields, selected)
                self._store_original(dialog, "driver", identifier, original, filename)
                self.reload_children()
                self.driver_select.setCurrentIndex(self.driver_select.findData(identifier))
                self.tabs.setCurrentIndex(1)
            else:
                selected = self.vehicle_id
                target = next((v for v in self.registry.vehicles(self.partner_id)
                               if v["id"] == selected), None)
                if target:
                    answer = QMessageBox.question(
                        self, "Автомобиль уже выбран",
                        "Дополнить выбранный автомобиль данными СТС? "
                        "Да — дополнить, Нет — новый автомобиль, Отмена — отменить.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                        QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
                    if answer == QMessageBox.StandardButton.Cancel:
                        return
                    if answer == QMessageBox.StandardButton.Yes:
                        merged = {key: target.get(key) or "" for key in VEHICLE_FIELDS}
                        merged.update(fields)
                        fields = merged
                    else:
                        selected = None
                identifier = self.registry.save_vehicle(fields, selected)
                self._store_original(dialog, "vehicle", identifier, original, filename)
                self.reload_children()
                self.vehicle_select.setCurrentIndex(self.vehicle_select.findData(identifier))
                self.tabs.setCurrentIndex(2)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Не сохранено", str(exc))

    def _store_original(self, dialog, kind, item_id, original, filename):
        if not dialog.keep_source.isChecked() or original is None:
            return
        try:
            DocumentArchive(self.registry.db).add(
                kind, item_id, original, filename or "Документ")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(
                self, "Карточка сохранена, оригинал — нет", str(exc))

    def _document_owner(self):
        kind = {0: "partner", 1: "driver", 2: "vehicle"}.get(self.tabs.currentIndex())
        identifier = {"partner": self.partner_id, "driver": self.driver_id,
                      "vehicle": self.vehicle_id}.get(kind)
        return kind, identifier

    def attach_documents(self):
        kind, identifier = self._document_owner()
        if identifier is None:
            QMessageBox.information(
                self, "Сначала сохрани карточку",
                "Выбери сохранённую организацию, водителя или автомобиль.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Добавить оригиналы документов", "",
            "Документы и изображения (*.pdf *.doc *.docx *.xls *.xlsx *.png *.jpg *.jpeg "
            "*.bmp *.webp *.txt *.rtf);;Все файлы (*.*)")
        if not paths:
            return
        try:
            archive = DocumentArchive(self.registry.db)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Защита документов", str(exc))
            return
        saved, failures = 0, []
        for raw in paths:
            source = Path(raw)
            try:
                if source.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("Размер более 20 МБ")
                archive.add(kind, identifier, source.read_bytes(), source.name)
                saved += 1
            except (ValueError, OSError) as exc:
                failures.append(f"{source.name}: {exc}")
        message = f"Документы в защищённой базе: {saved}."
        if failures:
            message += "\nНе сохранены:\n" + "\n".join(failures[:8])
        QMessageBox.information(self, "Добавление документов", message)

    def show_originals(self):
        kind = {0: "partner", 1: "driver", 2: "vehicle"}.get(self.tabs.currentIndex())
        identifier = {"partner": self.partner_id, "driver": self.driver_id,
                      "vehicle": self.vehicle_id}.get(kind)
        if identifier is None:
            QMessageBox.information(self, "Выбери карточку",
                                    "Сначала выбери организацию, водителя или автомобиль.")
            return
        try:
            archive = DocumentArchive(self.registry.db)
            rows = archive.items(kind, identifier)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Оригиналы", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "Оригиналы", "Для выбранной карточки файлов нет.")
            return
        labels = [f"{row['filename']} · {row['size'] // 1024 + 1} КБ · #{row['id']}"
                  for row in rows]
        selection, ok = QInputDialog.getItem(
            self, "Оригиналы документов", "Выбери файл:", labels, 0, False)
        if not ok:
            return
        record = rows[labels.index(selection)]
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Оригинал документа")
        dialog.setText(f"Файл: {record['filename']}")
        view_button = dialog.addButton("Просмотр / сохранить копию",
                                       QMessageBox.ButtonRole.ActionRole)
        delete_button = dialog.addButton("Удалить оригинал",
                                         QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is delete_button:
            answer = QMessageBox.question(
                self, "Удалить оригинал",
                "Точно удалить этот файл из защищённой базы? Карточка и реквизиты останутся.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                archive.delete(record["id"])
        elif dialog.clickedButton() is view_button:
            data = archive.get_bytes(record["id"])
            extension = Path(record["filename"]).suffix.casefold()
            if extension in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    viewer = QDialog(self)
                    viewer.setWindowTitle(record["filename"])
                    viewer.resize(850, 650)
                    layout = QVBoxLayout(viewer)
                    scroll = QScrollArea(viewer)
                    image = QLabel()
                    image.setPixmap(pixmap)
                    scroll.setWidget(image)
                    layout.addWidget(scroll)
                    viewer.exec()
                    return
            destination, _ = QFileDialog.getSaveFileName(
                self, "Сохранить копию документа", record["filename"])
            if destination:
                Path(destination).write_bytes(data)
                QMessageBox.information(
                    self, "Копия сохранена",
                    "Внимание: сохранённый вне LogistDesk файл больше не защищён "
                    "шифрованием приложения.")

    def import_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Импорт документов", "",
            "Документы (*.pdf *.docx *.xlsx *.png *.jpg *.jpeg *.bmp *.webp *.txt)")
        for path in paths:
            try:
                self._review(file_text(path), original=Path(path).read_bytes(), filename=Path(path).name)
            except Exception as exc:
                QMessageBox.warning(self, "Не удалось открыть файл", str(exc))

    def paste_clipboard(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        try:
            if mime.hasImage():
                self.import_image(clipboard.image())
            elif mime.hasText():
                self._review(clipboard.text())
            else:
                QMessageBox.information(self, "Буфер пуст", "Сначала сделай скрин через Win+Shift+S.")
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось распознать", str(exc))

    def import_image(self, image):
        if image.isNull():
            raise ValueError("Скриншот пуст")
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("Не удалось прочитать скриншот")
        if buffer.size() > 20 * 1024 * 1024:
            raise ValueError("Скриншот слишком большой")
        binary = bytes(buffer.data())
        kind, identifier = self._document_owner()
        if identifier is not None and self.registry.db.vault is not None:
            # Only persist private screenshots when the profile is encrypted.
            # In plain test profiles, allow OCR review without a blocking warning.
            DocumentArchive(self.registry.db).add(
                kind, identifier, binary, "Скриншот.png")
            answer = QMessageBox.question(
                self, "Скриншот сохранён",
                "Изображение добавлено в карточку. Также попробовать распознать реквизиты?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._review(image_text(binary), original=binary, filename="Скриншот.png")

    def export_contacts_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Защищённый экспорт базы", "LogistDesk_контакты.ldx",
            "Защищённая база (*.ldx)")
        if not path:
            return
        include_private = QMessageBox.question(
            self, "Персональные данные",
            "Включать паспортные данные, водительские удостоверения и СТС?\n"
            "Без явного разрешения эти поля не будут экспортированы.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        phrase, ok = QInputDialog.getText(
            self, "Защита экспорта", "Придумай отдельную парольную фразу от 12 символов:",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        verify, ok = QInputDialog.getText(
            self, "Подтвердить пароль", "Повтори парольную фразу:",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        if phrase != verify:
            QMessageBox.warning(self, "Пароли не совпали", "Экспорт отменён.")
            return
        try:
            result = export_contacts(self.registry, path, phrase, include_private=include_private)
            QMessageBox.information(self, "Экспортировано",
                f"Компаний: {result['companies']}.\\n"
                "Файл зашифрован. Не теряй пароль — без него импорт невозможен.")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Ошибка экспорта", str(exc))

    def import_contacts_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт защищённых контактов", "", "Защищённая база (*.ldx)")
        if not path:
            return
        phrase, ok = QInputDialog.getText(
            self, "Пароль импорта", "Парольная фраза для этого файла:",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            report = import_contacts(self.registry, path, phrase)
            self.reload_partners()
            QMessageBox.information(self, "Контакты перенесены",
                f"Новых компаний: {report['new_companies']}\\n"
                f"Ранее существовали: {report['existing_companies']}\\n"
                f"Водителей: {report['drivers']}\\n"
                f"Автомобилей: {report['vehicles']}\\n"
                f"Полей с отличиями (оставлены исходные): {report['conflicts']}")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Импорт не выполнен", str(exc))

    def toggle_folder_sync(self):
        if self.folder_sync is not None:
            self.sync_timer.stop()
            self.folder_sync.close()
            self.folder_sync = None
            self.sync_button.setText("Автообмен контактами: выключен")
            return
        answer = QMessageBox.question(
            self, "Защищённый обмен контактами",
            "Выбери папку, синхронизируемую между твоими устройствами. "
            "Обмениваться можно только данными, которые разрешено переносить.\\n"
            "Отправляются только зашифрованные копии контактов, рейсы и PIN не передаются. "
            "Пароль хранится только пока приложение работает. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "Выбери общую защищённую папку")
        if not folder:
            return
        include_private = QMessageBox.question(
            self, "Передача документов",
            "Переносить также паспортные данные, права и СТС?\\n"
            "По умолчанию эти поля исключены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        phrase, ok = QInputDialog.getText(
            self, "Пароль синхронизации",
            "Парольная фраза от 12 символов — одинаковая на обоих устройствах:",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            self.folder_sync = FolderSync(
                self.registry, folder, phrase, include_private=include_private)
            self.run_folder_sync()
            if self.folder_sync is not None:
                self.sync_timer.start()
                self.sync_button.setText("Автообмен: включён (нажми для выключения)")
        except (ValueError, OSError) as exc:
            self.folder_sync = None
            QMessageBox.warning(self, "Обмен не включён", str(exc))

    def run_folder_sync(self):
        if self.folder_sync is None:
            return
        try:
            result = self.folder_sync.sync_once()
            if result["files_received"] or result["new_companies"]:
                self.reload_partners()
            if result["conflicts"]:
                QMessageBox.information(
                    self, "Синхронизация без перезаписи",
                    f"Обнаружено {result['conflicts']} разных значений. "
                    "Исходные данные не заменены автоматически.")
        except (ValueError, OSError) as exc:
            self.sync_timer.stop()
            if self.folder_sync is not None:
                self.folder_sync.close()
                self.folder_sync = None
            self.sync_button.setText("Автообмен: остановлен (ошибка)")
            QMessageBox.warning(self, "Не удалось синхронизировать контакты", str(exc))

    def import_existing_calls(self):
        answer = QMessageBox.question(
            self, "Перенести старые контакты",
            "Создать справочник из сохранённых звонков? История рейсов не изменится.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = import_legacy_calls(self.registry)
            self.reload_partners()
            QMessageBox.information(self, "Готово",
                f"Обработано звонков: {result['total']}.\n"
                f"Связано со справочником: {result['linked']}.\n"
                f"Без названия перевозчика: {result['skipped']}.")
        except Exception as exc:
            QMessageBox.warning(self, "Импорт не завершён", str(exc))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            for path in paths:
                try:
                    kind, identifier = self._document_owner()
                    if identifier is not None:
                        DocumentArchive(self.registry.db).add(
                            kind, identifier, Path(path).read_bytes(), Path(path).name)
                    else:
                        self._review(file_text(path), original=Path(path).read_bytes(),
                                     filename=Path(path).name)
                except Exception as exc:
                    QMessageBox.warning(self, "Ошибка импорта", str(exc))
        elif event.mimeData().hasImage():
            try:
                from PySide6.QtGui import QImage
                self.import_image(QImage(event.mimeData().imageData()))
            except Exception as exc:
                QMessageBox.warning(self, "Ошибка импорта", str(exc))
        event.acceptProposedAction()
