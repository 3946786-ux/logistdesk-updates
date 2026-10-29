"""LogistDesk 1.1 — рабочая версия с коротким PIN и автообновлением."""
from __future__ import annotations
import sys
import os
import time
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QEvent, QRegularExpression, Signal, QTimer, QLocale, QTranslator, QLibraryInfo
from PySide6.QtGui import QFont, QIntValidator, QColor, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QInputDialog,
    QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
    QSystemTrayIcon, QMenu, QTabWidget,
)
from error_logging import configure_logging, install_exception_hook, log_exception, log_directory
from database import Database, default_data_dir
from security import SecurityVault, VaultError
from auth_ui import CreateAccountDialog, LoginDialog, PinSetupDialog
from theme import STYLESHEET
from trips_ui import (build_trips, adapt_trips, refresh_summary, update_trip_footer,
                      update_route_columns, status_chips, TRIPS_STYLE)
from route_display import trip_display_fields, route_status_parts
from ui_common import style_combo_popup, apply_dark_palette, localized_question, RussianMessageBox as QMessageBox
from ui_tracking import CloseRouteDialog, DateTimeDialog, AutoStartDialog
from tracking import display_datetime, reminder_title
from version import APP_VERSION
from updates import (UpdateError, manifest_url as update_manifest_url, newer_manifest,
                     download_package, launch_updater)
from call_card import PAYMENT_TERMS, arrival_for_edit, call_answers
from route_search import matching_routes, route_result_label
from excel_import import import_excel
from rules import (
    BODIES, CARRIER_STATUSES, CUSTOMER_STATUSES, CUSTOMER_VAT_OPTIONS, LOADING,
    PACKAGES, ROUTE_STATUSES, SENDERS, VAT_OPTIONS, DEFAULT_MARKUP_PERCENT,
    DEFAULT_FIXED_FEE, DEFAULT_PERSONAL_PERCENT, card_text, money, money_precise,
    net_rate, route_label, sender_conditions, sender_dimensions, parse_money, parse_percent, quote_calculation,
)


def app_asset(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "assets" / name


def app_icon() -> QIcon:
    # ICO contains multiple native Windows sizes, unlike a PNG-only taskbar icon.
    icon_path = app_asset("logistdesk.ico")
    return QIcon(str(icon_path if icon_path.is_file() else app_asset("logistdesk.png")))


def set_windows_app_id() -> None:
    """Keep our window and tray grouped as LogistDesk instead of Python."""
    if os.name != "nt":
        return
    try:
        import ctypes
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.c_long
        set_id("LogistDesk.Desktop")
    except (AttributeError, OSError):
        pass


def heading(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont("Segoe UI", 22)
    font.setBold(True)
    label.setFont(font)
    return label


class SmartCombo(QComboBox):
    """Editable searchable combobox: type, arrows, Enter, or custom answer."""
    def wheelEvent(self, event):
        # Scrolling a long dialog must not silently change a selected option.
        event.ignore()


class RoutePicker(SmartCombo):
    """Search routes, but never silently save a previously selected route."""
    def currentData(self, role=Qt.ItemDataRole.UserRole):
        index = self.findText(self.currentText(), Qt.MatchFlag.MatchExactly)
        return self.itemData(index, role) if index >= 0 else None


class RouteSearchPanel(QWidget):
    """Type a route in ordinary words; select an exact ID before saving."""
    routeSelected = Signal(object)

    def __init__(self, routes: list[dict], parent=None):
        super().__init__(parent)
        self.routes = list(routes)
        self.routes_by_id = {route["id"]: route for route in routes}
        self._selected_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Набережные Челны Москва, тоннаж или ID…")
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setObjectName("routeResults")
        self.results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results.setMaximumHeight(258)
        self.results.setMinimumHeight(54)
        layout.addWidget(self.results)
        self.selected_label = QLabel("Рейс ещё не выбран")
        self.selected_label.setObjectName("muted")
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)
        self.search.textChanged.connect(self.on_search_changed)
        self.search.returnPressed.connect(self.choose_current)
        self.results.itemClicked.connect(self.choose_item)
        self.results.itemActivated.connect(self.choose_item)
        self.update_results("")

    def update_results(self, query: str):
        matches = matching_routes(self.routes, query)
        self.results.clear()
        for route in matches:
            item = QListWidgetItem(route_result_label(route))
            item.setData(Qt.ItemDataRole.UserRole, route["id"])
            item.setSizeHint(QSize(0, 53 if "\n" in item.text() else 38))
            self.results.addItem(item)
        if matches:
            self.results.setCurrentRow(0)
            self.results.setVisible(True)
        else:
            self.results.setVisible(False)
        self.selected_label.setText("" if matches else "Совпадений нет")

    def on_search_changed(self, query: str):
        if self._selected_id is not None:
            self._selected_id = None
            self.routeSelected.emit(None)
        self.update_results(query)

    def choose_current(self):
        item = self.results.currentItem()
        if not self.results.isHidden() and item is not None:
            self.choose_item(item)

    def choose_item(self, item: QListWidgetItem):
        self.select_route(item.data(Qt.ItemDataRole.UserRole))

    def select_route(self, route_id: str | None):
        route = self.routes_by_id.get(route_id)
        if route is None:
            self._selected_id = None
            self.routeSelected.emit(None)
            return
        self._selected_id = route["id"]
        self.search.blockSignals(True)
        self.search.setText(f"{route.get('origin') or '?'} → {route.get('destination') or '?'}")
        self.search.blockSignals(False)
        self.results.hide()
        self.selected_label.setText("Выбран: " + route_label(route))
        self.routeSelected.emit(route)

    def currentData(self):
        return self._selected_id

    def currentText(self):
        route = self.routes_by_id.get(self._selected_id)
        return route_label(route) if route else self.search.text()

    def focus_search(self):
        self.search.setFocus()
        if self._selected_id is None:
            self.search.selectAll()


class PillChoice(QWidget):
    """One-click alternatives for short lists; no dropdown or mouse wheel."""
    valueChanged = Signal(str)

    def __init__(self, options: list[str], value: str = "", parent=None):
        super().__init__(parent)
        self._buttons = {}
        self._selected = ""
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        for option in options:
            button = QPushButton(option)
            button.setObjectName("pill")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, v=option: self.set_value(v))
            line.addWidget(button)
            self._buttons[option] = button
        line.addStretch(1)
        self.set_value(value, notify=False)

    def set_value(self, value: str, *, notify=True):
        value = value if value in self._buttons else next(iter(self._buttons))
        self._selected = value
        for label, button in self._buttons.items():
            button.setChecked(label == value)
        if notify:
            self.valueChanged.emit(self.currentText())

    def currentText(self) -> str:
        return "" if self._selected in ("Не уточнил", "Не указан") else self._selected


def combo(items: list[str], *, editable=True) -> QComboBox:
    widget = SmartCombo()
    widget.addItems(items)
    widget.setEditable(editable)
    widget.setMinimumWidth(145)
    if editable:
        widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        widget.lineEdit().setClearButtonEnabled(True)
        completer = QCompleter(widget.model(), widget)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setMaxVisibleItems(9)
        widget.setCompleter(completer)
    style_combo_popup(widget)
    return widget


def route_picker(routes: list[dict], selected: str | None = None) -> RoutePicker:
    picker = RoutePicker()
    picker.setEditable(True)
    picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    picker.lineEdit().setPlaceholderText("Начни вводить город или ID рейса…")
    picker.lineEdit().setClearButtonEnabled(True)
    for route in routes:
        picker.addItem(route_label(route), route["id"])
    completer = QCompleter(picker.model(), picker)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setMaxVisibleItems(9)
    picker.setCompleter(completer)
    picker.completer().popup().setMinimumWidth(650)
    style_combo_popup(picker)
    if selected:
        index = picker.findData(selected)
        if index >= 0:
            picker.setCurrentIndex(index)
    return picker


def select_combo(widget: QComboBox, text: str) -> None:
    if text:
        idx = widget.findText(text)
        if idx >= 0:
            widget.setCurrentIndex(idx)
        elif widget.isEditable():
            widget.setEditText(text)


def text_field(value=None, *, placeholder="", money_field=False) -> QLineEdit:
    item = QLineEdit(str(value) if value not in (None, "") else "")
    item.setPlaceholderText(placeholder)
    if money_field:
        item.setValidator(QIntValidator(0, 1000000000))
    return item


def text_area(value="", height=76) -> QPlainTextEdit:
    widget = QPlainTextEdit(str(value or ""))
    widget.setMinimumHeight(height)
    return widget


def get_value(widget):
    if isinstance(widget, (QComboBox, PillChoice)):
        return widget.currentText().strip()
    if isinstance(widget, QPlainTextEdit):
        return widget.toPlainText().strip()
    return widget.text().strip()


class RouteDialog(QDialog):
    def __init__(self, db: Database, record: dict | None = None, parent=None):
        super().__init__(parent)
        self.record = record or {}
        self.setWindowTitle("Редактирование рейса" if record else "Добавить рейс")
        self.resize(690, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        contents = QWidget()
        form = QFormLayout(contents)
        form.setSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.fields = {}
        self.fields["id"] = text_field(self.record.get("id") or db.next_route_id())
        self.fields["id"].setReadOnly(True)
        form.addRow("ID рейса", self.fields["id"])
        for key, caption, options in [
            ("sender", "Отправитель", SENDERS),
            ("origin", "Откуда", None), ("destination", "Куда", None),
            ("cargo", "Груз / описание", None), ("dimensions", "Габариты", None),
            ("package_type", "Упаковка", PACKAGES), ("places", "Количество мест", None),
            ("weight", "Вес / объём", None), ("loading", "Способ загрузки", LOADING),
        ]:
            widget = combo([""] + options if options and options[0] != "" else options, editable=True) if options else text_field()
            if self.record.get(key) is not None:
                if isinstance(widget, QComboBox):
                    select_combo(widget, str(self.record.get(key) or ""))
                else:
                    widget.setText(str(self.record.get(key) or ""))
            self.fields[key] = widget
            form.addRow(caption, widget)
        self.fields["sender_conditions"] = text_area(self.record.get("sender_conditions"))
        self.fields["own_conditions"] = text_area(self.record.get("own_conditions"))
        form.addRow("Условия отправителя", self.fields["sender_conditions"])
        form.addRow("Условия рейса (свои)", self.fields["own_conditions"])
        self.fields["with_vat"] = text_field(self.record.get("with_vat"), money_field=True)
        self.fields["with_vat"].setPlaceholderText("Первоначальная ставка для ATI, НЕ цена заказчика")
        form.addRow("Ставка на ATI с НДС, ₽", self.fields["with_vat"])
        self.enabled = QCheckBox("Есть ставка без НДС")
        self.enabled.setChecked(bool(self.record.get("has_without_vat")))
        form.addRow("", self.enabled)
        self.fields["manual_without_vat"] = text_field(self.record.get("manual_without_vat"), money_field=True)
        self.fields["manual_without_vat"].setPlaceholderText("Пусто — считать автоматически")
        form.addRow("Ставка на ATI без НДС, ₽", self.fields["manual_without_vat"])
        self.net_preview = QLabel("")
        form.addRow("Итог без НДС", self.net_preview)
        self.fields["date_window"] = text_field(self.record.get("date_window"))
        self.fields["date_window"].setPlaceholderText("Например: 01.10, 08:00–10:00")
        form.addRow("Загрузка", self.fields["date_window"])
        self.fields["unload_window"] = text_field(self.record.get("unload_window"))
        self.fields["unload_window"].setPlaceholderText("Например: 02.10, до 15:00")
        form.addRow("Выгрузка", self.fields["unload_window"])
        self.fields["status"] = text_field(self.record.get("status") or "Выложен")
        self.fields["status"].setReadOnly(True)
        form.addRow("Статус (только просмотр)", self.fields["status"])
        self.fields["note"] = text_area(self.record.get("note"))
        form.addRow("Примечание", self.fields["note"])
        scroll.setWidget(contents)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        controls.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        controls.accepted.connect(self.validate_and_accept)
        controls.rejected.connect(self.reject)
        outer.addWidget(controls)
        self._last_suggestion = self.record.get("sender_conditions") or ""
        self._last_dimensions_suggestion = ""
        self.fields["sender"].currentTextChanged.connect(self.update_sender_suggestion)
        self.fields["sender"].currentTextChanged.connect(self.update_dimensions_suggestion)
        self.fields["cargo"].textChanged.connect(self.update_sender_suggestion)
        self.fields["with_vat"].textChanged.connect(self.update_rate_preview)
        self.fields["manual_without_vat"].textChanged.connect(self.update_rate_preview)
        self.enabled.toggled.connect(self.update_rate_preview)
        self.update_rate_preview()
        if not record:
            self.update_sender_suggestion()
        if not get_value(self.fields["dimensions"]):
            self.update_dimensions_suggestion()

    def update_dimensions_suggestion(self, *_):
        target = self.fields["dimensions"]
        current = target.text().strip()
        if current and current != self._last_dimensions_suggestion:
            return
        suggestion = sender_dimensions(get_value(self.fields["sender"]))
        target.setText(suggestion)
        self._last_dimensions_suggestion = suggestion

    def update_sender_suggestion(self, *_):
        target = self.fields["sender_conditions"]
        current = target.toPlainText().strip()
        # Ручное изменение условия никогда не стираем.
        if current and current != self._last_suggestion:
            return
        suggestion = sender_conditions(get_value(self.fields["sender"]), get_value(self.fields["cargo"]))
        target.setPlainText(suggestion)
        self._last_suggestion = suggestion

    def update_rate_preview(self, *_):
        try:
            value = net_rate(get_value(self.fields["with_vat"]), self.enabled.isChecked(), get_value(self.fields["manual_without_vat"]))
            self.net_preview.setText(money(value) if value is not None else "—")
        except ValueError:
            self.net_preview.setText("Некорректная сумма")

    def payload(self) -> dict:
        result = {k: get_value(v) for k, v in self.fields.items()}
        result["has_without_vat"] = int(self.enabled.isChecked())
        result["with_vat"] = parse_money(result["with_vat"])
        result["manual_without_vat"] = parse_money(result["manual_without_vat"])
        return result

    def validate_and_accept(self):
        if not get_value(self.fields["origin"]) or not get_value(self.fields["destination"]):
            QMessageBox.warning(self, "Заполни маршрут", "Укажи пункты загрузки и выгрузки.")
            return
        try:
            self.payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверь ставку", str(exc))
            return
        self.accept()


class CarrierDialog(QDialog):
    """Short, inline phone-call card. Financial and historical details stay optional."""
    def __init__(self, db: Database, record: dict | None = None, preferred_route: str | None = None, parent=None):
        super().__init__(parent)
        self.record = record or {}
        self.setWindowTitle("Новый звонок · LogistDesk" if not record else "Редактировать звонок · LogistDesk")
        self.resize(1200, 740)
        self.setMinimumWidth(980)
        self.fields = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 18, 26, 16)
        title = heading("Новый звонок" if not record else "Редактирование звонка")
        header_layout.addWidget(title)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(scroll)
        root.addWidget(splitter, 1)
        contents = QWidget()
        contents.setObjectName("dialogContents")
        content = QVBoxLayout(contents)
        content.setContentsMargins(24, 18, 24, 20)
        content.setSpacing(14)
        scroll.setWidget(contents)

        # The route preview is visible during the entire call, even while the
        # left-hand form scrolls. Nothing must be opened in a separate tab.
        right_panel = QFrame()
        right_panel.setObjectName("routePreview")
        right_panel.setMinimumWidth(330)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(12)
        preview_title = QLabel("Карточка рейса")
        preview_title.setObjectName("sectionTitle")
        right_layout.addWidget(preview_title)
        self.route_preview_label = QLabel("Сначала выбери рейс слева")
        self.route_preview_label.setObjectName("muted")
        self.route_preview_label.setWordWrap(True)
        right_layout.addWidget(self.route_preview_label)
        self.route_preview = QPlainTextEdit()
        self.route_preview.setReadOnly(True)
        self.route_preview.setPlaceholderText("Маршрут, груз, тоннаж, палеты, загрузка и условия появятся здесь.")
        self.route_preview.setFont(QFont("Segoe UI", 11))
        self.route_preview.setStyleSheet(
            "QPlainTextEdit { background: #202c39; border: 1px solid #354657; "
            "border-radius: 8px; padding: 12px; color: #e4ebf2; }"
        )
        right_layout.addWidget(self.route_preview, 1)
        copy_route = QPushButton("Копировать карточку рейса")
        copy_route.clicked.connect(self.copy_route_preview)
        right_layout.addWidget(copy_route)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([745, 495])

        basic, basic_layout = self.card("Рейс и контакт", "")
        basic_form = QFormLayout()
        basic_form.setSpacing(10)
        basic_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.route = RouteSearchPanel(db.routes(include_closed=bool(record)))
        self.route.routeSelected.connect(self.update_route_preview)
        basic_layout.addWidget(self.route)
        self.fields["carrier"] = text_field(self.record.get("carrier"), placeholder="Имя или название, если известно")
        basic_form.addRow("Перевозчик", self.fields["carrier"])
        self.fields["phone"] = text_field(self.record.get("phone"), placeholder="Телефон, если известен")
        basic_form.addRow("Телефон", self.fields["phone"])
        self.fields["driver_phone"] = text_field(self.record.get("driver_phone"), placeholder="Телефон водителя")
        basic_form.addRow("Телефон водителя", self.fields["driver_phone"])
        basic_layout.addLayout(basic_form)
        self.history_hint = QLabel("")
        self.history_hint.setObjectName("muted")
        self.history_hint.setWordWrap(True)
        basic_layout.addWidget(self.history_hint)
        self.use_history = QPushButton("Подставить имя из истории")
        self.use_history.hide()
        basic_layout.addWidget(self.use_history)
        self.fields["phone"].editingFinished.connect(lambda: self.lookup_phone(db))
        content.addWidget(basic)

        questions, question_layout = self.card("Звонок", "", "callCard")
        self.fields["body"] = combo(BODIES)
        self.fields["body"].lineEdit().setPlaceholderText("Начни писать: тент, изотерм, термос…")
        select_combo(self.fields["body"], str(self.record.get("body") or ""))
        self.question_row(question_layout, "Какая машина?", self.fields["body"])

        self.fields["arrival_date"] = text_field(arrival_for_edit(self.record), placeholder="Например: завтра / 30.09 / завтра к 10:00")
        self.question_row(question_layout, "Когда будете на загрузке?", self.fields["arrival_date"])

        self.fields["partial_load"] = PillChoice(["Не уточнил", "Да", "Нет"], self.record.get("partial_load") or "Не уточнил")
        self.question_row(question_layout, "Есть догруз?", self.fields["partial_load"])

        self.fields["etrn"] = PillChoice(["Не уточнил", "Да", "Нет"], self.record.get("etrn") or "Не уточнил")
        self.question_row(question_layout, "Работаете с ЭТрН?", self.fields["etrn"])
        self.fields["etrn_provider"] = text_field(self.record.get("etrn_provider"), placeholder="Например: Контур")
        self.provider_row = QWidget()
        provider_layout = QHBoxLayout(self.provider_row)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        provider_layout.setSpacing(14)
        provider_label = QLabel("Какой оператор ЭТрН?")
        provider_label.setFixedWidth(265)
        provider_layout.addWidget(provider_label)
        provider_layout.addWidget(self.fields["etrn_provider"], 1)
        question_layout.addWidget(self.provider_row)
        self.fields["etrn"].valueChanged.connect(self.update_provider_visibility)
        self.update_provider_visibility()

        self.payment_spoken = QCheckBox("Сообщил: оплата по оригиналам, 10–15 б.д.")
        self.payment_spoken.setChecked(bool(self.record.get("payment_terms_communicated", 0)))
        self.question_row(question_layout, "Условия оплаты", self.payment_spoken)
        self.payment_spoken.toggled.connect(self.fill_payment_terms)
        content.addWidget(questions)

        finance, finance_layout = self.card("Ставка и согласование", "", "financeCard")
        finance_form = QFormLayout()
        finance_form.setSpacing(10)
        finance_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.fields["desired_rate"] = text_field(self.record.get("desired_rate"), placeholder="Сколько просит перевозчик, ₽", money_field=True)
        finance_form.addRow("Перевозчик просит", self.fields["desired_rate"])
        self.fields["vat_type"] = PillChoice(["Не указан", "С НДС", "Без НДС"], self.record.get("vat_type") or "Не указан")
        finance_form.addRow("Ставка перевозчика", self.fields["vat_type"])
        self.fields["customer_status"] = PillChoice(CUSTOMER_STATUSES, self.record.get("customer_status") or "Не отправлено")
        finance_form.addRow("Согласование", self.fields["customer_status"])
        self.fields["customer_agreed_rate"] = text_field(self.record.get("customer_agreed_rate"), placeholder="Заполни, если заказчик согласовал", money_field=True)
        finance_form.addRow("Подтверждённая ставка", self.fields["customer_agreed_rate"])
        finance_layout.addLayout(finance_form)
        self.pricing_preview = QLabel()
        self.pricing_preview.setWordWrap(True)
        self.pricing_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pricing_preview.setStyleSheet(
            "background: #243443; border: 1px solid #354b5d; border-radius: 8px; "
            "padding: 12px; color: #d7e8f6;"
        )
        finance_layout.addWidget(self.pricing_preview)
        content.addWidget(finance)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("advancedToggle")
        self.advanced_toggle.setText("▸ Дополнительно: статус, перезвон, настройки ставки")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        content.addWidget(self.advanced_toggle)
        self.advanced_box, advanced_layout = self.card("Дополнительные сведения", "")
        advanced_form = QFormLayout()
        advanced_form.setSpacing(10)
        advanced_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        optional_fields = [
            ("loading", "Способ загрузки", LOADING),
            ("call_date", "Дата звонка", None),
            ("driver_name", "Имя водителя", None),
            ("status", "Статус перевозчика", CARRIER_STATUSES),
            ("callback_date", "Перезвонить", None),
            ("payment", "Другие условия оплаты", None),
            ("markup_percent", "Наценка заказчику, %", None),
            ("fixed_fee", "Плюс к ставке, ₽", None),
            ("personal_percent", "Моя доля от маржи, %", None),
            ("customer_vat_type", "НДС заказчика", CUSTOMER_VAT_OPTIONS),
            ("comment", "Комментарий", None),
        ]
        defaults = {
            "markup_percent": DEFAULT_MARKUP_PERCENT, "fixed_fee": DEFAULT_FIXED_FEE,
            "personal_percent": DEFAULT_PERSONAL_PERCENT, "customer_vat_type": "Как у перевозчика",
            "status": "Новый",
        }
        for key, caption, options in optional_fields:
            value = self.record.get(key)
            if value in (None, "") and key in defaults:
                value = defaults[key]
            if options is not None:
                widget = combo(options, editable=key != "customer_vat_type")
                select_combo(widget, str(value or ""))
            elif key == "comment":
                widget = text_area(value, height=74)
            else:
                widget = text_field(value, money_field=key == "fixed_fee")
            self.fields[key] = widget
            advanced_form.addRow(caption, widget)
        advanced_layout.addLayout(advanced_form)
        content.addWidget(self.advanced_box)
        self.advanced_box.hide()
        if self.payment_spoken.isChecked():
            self.fill_payment_terms(True)

        for key in ("desired_rate", "customer_agreed_rate", "markup_percent", "fixed_fee", "personal_percent"):
            self.fields[key].textChanged.connect(self.update_pricing_preview)
        self.fields["vat_type"].valueChanged.connect(self.update_pricing_preview)
        self.fields["customer_status"].valueChanged.connect(self.update_pricing_preview)
        self.fields["customer_vat_type"].currentTextChanged.connect(self.update_pricing_preview)
        self.update_pricing_preview()

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 12)
        copy_quote = QPushButton("Копировать ставку заказчику")
        copy_quote.clicked.connect(self.copy_customer_quote)
        footer_layout.addWidget(copy_quote)
        footer_layout.addStretch(1)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        controls.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        # Enter in route search chooses a result; it must not save the dialog.
        controls.button(QDialogButtonBox.StandardButton.Save).setAutoDefault(False)
        controls.button(QDialogButtonBox.StandardButton.Save).setDefault(False)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        controls.accepted.connect(self.validate_and_accept)
        controls.rejected.connect(self.reject)
        footer_layout.addWidget(controls)
        root.addWidget(footer)
        self.route.select_route(self.record.get("route_id") or preferred_route)
        if not self.route.currentData():
            self.route.focus_search()

    def lookup_phone(self, db: Database):
        from rules import normalize_phone
        number = self.fields["phone"].text().strip()
        self.history_hint.clear()
        self.use_history.hide()
        if not normalize_phone(number):
            return
        matches = db.phone_history(number, exclude_id=self.record.get("id"))
        if not matches:
            return
        previous = matches[0]
        self.history_hint.setText(
            f"Уже звонил: {len(matches)} записей. Последний контакт: "
            f"{previous.get('carrier') or 'без имени'}, ставка {money(previous.get('desired_rate')) or '—'}."
        )
        if previous.get("carrier") and not self.fields["carrier"].text().strip():
            try:
                self.use_history.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.use_history.clicked.connect(
                lambda checked=False, name=previous["carrier"]: self.fields["carrier"].setText(name))
            self.use_history.show()

    def update_route_preview(self, route: dict | None):
        if route is None:
            self.route_preview_label.setText("Сначала выбери рейс слева")
            self.route_preview.clear()
            return
        self.route_preview_label.setText(route_label(route))
        self.route_preview.setPlainText(card_text(route))
        self.route_preview.verticalScrollBar().setValue(0)

    def copy_route_preview(self):
        if not self.route.currentData():
            QMessageBox.information(self, "Выбери рейс", "Сначала выбери нужный рейс из результатов поиска.")
            return
        QApplication.clipboard().setText(self.route_preview.toPlainText())

    @staticmethod
    def card(title: str, description: str, name: str = "surfaceCard"):
        frame = QFrame()
        frame.setObjectName(name)
        box = QVBoxLayout(frame)
        box.setContentsMargins(18, 16, 18, 18)
        box.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        box.addWidget(title_label)
        if description:
            helper = QLabel(description)
            helper.setObjectName("muted")
            helper.setWordWrap(True)
            box.addWidget(helper)
        return frame, box

    @staticmethod
    def question_row(layout: QVBoxLayout, question: str, field: QWidget):
        row = QHBoxLayout()
        row.setSpacing(14)
        label = QLabel(question)
        label.setFixedWidth(265)
        row.addWidget(label)
        row.addWidget(field, 1)
        layout.addLayout(row)

    def toggle_advanced(self, checked: bool):
        self.advanced_box.setVisible(checked)
        self.advanced_toggle.setText(("▾" if checked else "▸") + " Дополнительно: статус, перезвон, настройки ставки")

    def update_provider_visibility(self, *_):
        self.provider_row.setVisible(get_value(self.fields["etrn"]) == "Да")

    def fill_payment_terms(self, checked: bool):
        if checked and "payment" in self.fields and not get_value(self.fields["payment"]):
            self.fields["payment"].setText(PAYMENT_TERMS)

    def payload(self) -> dict:
        result = {key: get_value(widget) for key, widget in self.fields.items()}
        result.update(call_answers(
            self.record, body=result["body"], arrival=result["arrival_date"],
            etrn=result["etrn"], provider=result["etrn_provider"],
            payment_confirmed=self.payment_spoken.isChecked(), payment=result["payment"],
            partial_load=result["partial_load"],
        ))
        result["route_id"] = self.route.currentData()
        result["source_key"] = self.record.get("source_key")
        result["desired_rate"] = parse_money(result["desired_rate"])
        result["customer_agreed_rate"] = parse_money(result["customer_agreed_rate"])
        result["fixed_fee"] = parse_money(result["fixed_fee"])
        result["markup_percent"] = str(parse_percent(result["markup_percent"], maximum=1000))
        result["personal_percent"] = str(parse_percent(result["personal_percent"]))
        quote_calculation(result)
        return result

    def update_pricing_preview(self, *_):
        try:
            result = quote_calculation({key: get_value(widget) for key, widget in self.fields.items()})
        except ValueError as exc:
            self.pricing_preview.setText(f"Проверь введённые суммы: {exc}")
            return
        if result["requested_rate"] is None:
            self.pricing_preview.setText("Введи ставку перевозчика — предложение заказчику рассчитается автоматически.")
            return
        lines = [
            f"Предложить заказчику: {money(result['quote'])} "
            f"(перевозчик + {result['markup_percent']}% + {money(result['fixed_fee'])}).",
        ]
        if result["confirmed"]:
            lines.append(f"Заказчик подтвердил: {money(result['agreed_rate'])}.")
        elif result["customer_status"] == "Отказ":
            lines.append("Заказчик отказался: маржа и твоя доля не начисляются.")
        elif result["customer_status"] == "Согласовано":
            lines.append("Статус «Согласовано» выбран, но подтверждённая сумма не указана.")
        else:
            lines.append("Заказчик ещё не согласовал: маржа и твоя доля — предварительные.")
        if result["agreed_rate"] is not None and not result["confirmed"]:
            lines.append("Введённая сумма заказчика не влияет на расчёт до подтверждения.")
        if result["company_margin"] is not None:
            lines.append(f"Маржа компании: {money(result['company_margin'])}.")
            if result["personal_share"] is None:
                lines.append("Маржа отрицательная: твоя доля не рассчитана.")
            else:
                lines.append(f"Твоя доля ({result['personal_percent']}%): {money_precise(result['personal_share'])}.")
        if result["vat_warning"]:
            lines.append(result["vat_warning"])
        self.pricing_preview.setText("\n".join(lines))

    def copy_customer_quote(self):
        try:
            result = self.payload()
            calculation = quote_calculation(result)
        except ValueError as exc:
            QMessageBox.warning(self, "Проверь ставку", str(exc))
            return
        if calculation["quote"] is None:
            QMessageBox.information(self, "Нет ставки", "Сначала введи ставку перевозчика.")
            return
        route = self.route.currentText().split(" | ", 2)
        route_name = route[1] if len(route) > 1 else self.route.currentText()
        QApplication.clipboard().setText(
            f"По рейсу {route_name} предлагаемая ставка: {money(calculation['quote'])}."
        )
        QMessageBox.information(self, "Скопировано", "Предложение заказчику скопировано в буфер обмена.")

    def validate_and_accept(self):
        if not self.route.currentData():
            QMessageBox.warning(self, "Выбери рейс", "Выбери существующий рейс из подсказки.")
            return
        try:
            record = self.payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Проверь данные", str(exc))
            return
        if record["customer_status"] == "Согласовано" and record["customer_agreed_rate"] is None:
            QMessageBox.warning(self, "Нет подтверждённой ставки", "Введи сумму, которую согласовал заказчик.")
            return
        self.accept()


class LogistWindow(QMainWindow):
    update_checked = Signal(object, bool)
    update_check_failed = Signal(str, bool)
    update_downloaded = Signal(object, object)
    update_download_failed = Signal(str)

    def __init__(self, vault: SecurityVault | None = None):
        super().__init__()
        self.vault = vault
        self._security_locked = False
        self._last_interaction = time.monotonic()
        self._session_registered = False
        self.db = Database(vault=vault) if vault is not None else Database()
        self.setWindowTitle("LogistDesk · Рейсы и перевозчики")
        self.setWindowIcon(app_icon())
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        self.resize(min(1570, available.width() - 34) if available else 1570,
                    min(950, available.height() - 34) if available else 950)
        self.setMinimumSize(960, 560)
        self.archive_only = False
        self.deleted_only = False

        core = QWidget()
        self.setCentralWidget(core)
        overall = QHBoxLayout(core)
        overall.setContentsMargins(0, 0, 0, 0)
        overall.setSpacing(0)
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(254)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(17, 27, 17, 19)
        left.setSpacing(7)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        brand_mark = QLabel()
        brand_mark.setObjectName("brandMark")
        brand_mark.setPixmap(QPixmap(str(app_asset("logistdesk_mark.png"))).scaled(
            51, 51, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand_mark.setFixedSize(54, 54)
        brand_row.addWidget(brand_mark)
        brand = QLabel("LogistDesk")
        brand.setObjectName("brandName")
        brand_row.addWidget(brand, 1)
        left.addLayout(brand_row)
        subtitle = QLabel("Рейсы · Перевозчики · Контроль")
        subtitle.setObjectName("brandCaption")
        subtitle.setWordWrap(True)
        subtitle.setMinimumHeight(43)
        left.addWidget(subtitle)
        self.sidebar_labels = [brand, subtitle]
        left.addSpacing(29)
        nav_caption = QLabel("РАБОЧЕЕ ПРОСТРАНСТВО")
        nav_caption.setObjectName("navCaption")
        left.addWidget(nav_caption)
        self.sidebar_labels.append(nav_caption)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.addItems(["Сегодня", "Рейсы", "Машины", "Карточка рейса", "Архив", "Корзина"])
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setSpacing(6)
        self.navigation.setIconSize(QSize(22, 22))
        for index, name in enumerate(("today", "routes", "carriers", "card", "archive", "trash")):
            icon_path = app_asset(f"nav_{name}.png")
            if icon_path.is_file():
                self.navigation.item(index).setIcon(QIcon(str(icon_path)))
            self.navigation.item(index).setSizeHint(QSize(0, 52))
        left.addWidget(self.navigation, 1)
        footer = QLabel(f"LOGISTDESK · {APP_VERSION}\nЛокальные данные")
        footer.setObjectName("sidebarFooter")
        footer.setWordWrap(True)
        left.addWidget(footer)
        self.sidebar_labels.append(footer)
        overall.addWidget(sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(16, 14, 16, 10)
        right.setSpacing(17)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(3)
        self.page_title = heading("Сегодня")
        title_stack.addWidget(self.page_title)
        self.page_caption = QLabel("Напоминания и контроль перевозок")
        self.page_caption.setObjectName("pageCaption")
        self.page_caption.setWordWrap(True)
        title_stack.addWidget(self.page_caption)
        toolbar.addLayout(title_stack, 1)
        new_route = QPushButton("+ Новый рейс")
        new_route.setObjectName("newRoute")
        self.new_route_button = new_route
        new_route.clicked.connect(self.add_route)
        new_route.hide()
        toolbar.addWidget(new_route)
        new_call = QPushButton("+ Новый звонок")
        new_call.setObjectName("primary")
        self.new_call_button = new_call
        new_call.clicked.connect(self.add_carrier)
        toolbar.addWidget(new_call)
        more = QPushButton("Ещё")
        menu = QMenu(more)
        menu.addAction("Импорт из Excel", self.import_file)
        menu.addAction("Выгрузить CSV", self.export_file)
        menu.addAction("Резервная копия", self.backup)
        menu.addSeparator()
        menu.addAction("Проверить обновления", lambda: self.check_updates(manual=True))
        more.setMenu(menu)
        toolbar.addWidget(more)
        settings = QPushButton("Настройки")
        settings.clicked.connect(self.show_settings)
        toolbar.addWidget(settings)
        right.addLayout(toolbar)
        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)
        overall.addLayout(right, 1)
        self.make_today_page()
        self.make_routes_page()
        self.make_carriers_page()
        self.make_card_page()
        self.navigation.currentRowChanged.connect(self.navigate)
        self.navigation.setCurrentRow(1)
        self.statusBar().showMessage("LogistDesk · контроль рейсов")
        self.refresh_all()
        self._shown_due = {}
        self._really_quit = False
        self._tray_notice_shown = False
        self._update_checking = False
        self._update_downloading = False
        self.update_checked.connect(self._on_update_checked)
        self.update_check_failed.connect(self._on_update_check_failed)
        self.update_downloaded.connect(self._on_update_downloaded)
        self.update_download_failed.connect(self._on_update_download_failed)
        self.setup_tray()
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.poll_reminders)
        self.reminder_timer.start(45000)
        QTimer.singleShot(1500, self.poll_reminders)
        if update_manifest_url():
            QTimer.singleShot(2500, lambda: self.check_updates(manual=False))
        if self.vault is not None:
            # Do not lock/hide the application merely because it has been idle.
            # Windows session lock and explicit close-to-tray still protect the window.
            self._security_timer = QTimer(self)
            self._register_session_notifications()

    def eventFilter(self, watched, event):
        if self.vault is not None and not self._security_locked and event.type() in (
            QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel,
            QEvent.Type.TouchBegin):
            self._last_interaction = time.monotonic()
        return super().eventFilter(watched, event)

    def _check_idle_lock(self):
        # 1.1: inactivity never closes or locks LogistDesk.
        return

    def _lock_app(self):
        if self.vault is None or self._security_locked or self._really_quit:
            return
        self._security_locked = True
        # An open edit dialog must not remain visible after the parent is hidden.
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self:
            if isinstance(modal, QDialog):
                modal.reject()
            else:
                modal.hide()
        self.hide()
        if not self._tray_available:
            QTimer.singleShot(0, self.show_from_tray)

    def _register_session_notifications(self):
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            register = ctypes.windll.wtsapi32.WTSRegisterSessionNotification
            register.argtypes = [wintypes.HWND, wintypes.DWORD]
            register.restype = wintypes.BOOL
            self._session_registered = bool(register(int(self.winId()), 0))
        except (AttributeError, OSError, ValueError):
            self._session_registered = False

    def nativeEvent(self, event_type, message):
        if self.vault is not None and self._session_registered and os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x02B1 and msg.wParam == 0x7:  # WTS_SESSION_LOCK
                    self._lock_app()
            except (AttributeError, OSError, ValueError, TypeError):
                pass
        return super().nativeEvent(event_type, message)

    def navigate(self, index: int):
        self.centralWidget().setStyleSheet(TRIPS_STYLE if index in (1, 4, 5) else "")
        self.new_call_button.setText("+ Новый звонок")
        self.new_route_button.setVisible(index == 1)
        self.route_filter = "all"
        if index in (1, 4, 5):
            self._trips_compact_detail = False
        adapt_trips(self)
        self.archive_only = index == 4
        self.deleted_only = index == 5
        page = 1 if index in (4, 5) else index
        if 0 <= page < self.pages.count():
            self.pages.setCurrentIndex(page)
        titles = ["Сегодня", "Рейсы", "Машины", "Карточка рейса", "Архив", "Корзина"]
        if 0 <= index < len(titles):
            self.page_title.setText(titles[index])
            captions = (
                "Напоминания и контроль перевозок",
                "Управляй рейсами, перевозчиками и документами",
                "Все звонки и предложения перевозчиков",
                "Информация о рейсе для отправки перевозчику",
                "Рейсы, которые ты перенёс в архив",
                "Удалённые рейсы можно восстановить",
            )
            self.page_caption.setText(captions[index])
        if index in (1, 4, 5):
            self.refresh_routes()

    def create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(56)
        table.setShowGrid(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return table

    def make_today_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setSpacing(12)
        top = QHBoxLayout()
        self.today_title = heading("Сегодня · контроль перевозок")
        top.addWidget(self.today_title)
        top.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh_today)
        top.addWidget(refresh)
        outer.addLayout(top)
        self.today_table = self.create_table(["Когда", "Рейс", "Что сделать", "Водитель / телефон", "Состояние"])
        self.today_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for index, width in ((0, 145), (1, 280), (3, 220), (4, 120)):
            self.today_table.setColumnWidth(index, width)
        self.today_table.itemSelectionChanged.connect(self.on_today_selection)
        outer.addWidget(self.today_table, 3)
        detail = QFrame()
        detail.setObjectName("dashboardCard")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(16, 14, 16, 14)
        self.today_detail = QLabel("Выбери напоминание, чтобы увидеть подробности и номер водителя.")
        self.today_detail.setWordWrap(True)
        self.today_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.today_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self.today_detail)
        controls = QHBoxLayout()
        self.today_action_button = QPushButton("Подтвердить выполнение")
        self.today_action_button.setObjectName("primary")
        self.today_action_button.clicked.connect(self.perform_today_action)
        controls.addWidget(self.today_action_button)
        self.today_snooze_button = QPushButton("Через 30 минут")
        self.today_snooze_button.clicked.connect(self.snooze_today)
        controls.addWidget(self.today_snooze_button)
        self.today_change_button = QPushButton("Изменить время")
        self.today_change_button.clicked.connect(self.change_today_time)
        controls.addWidget(self.today_change_button)
        self.today_copy_phone = QPushButton("Копировать номер")
        self.today_copy_phone.clicked.connect(self.copy_today_phone)
        controls.addWidget(self.today_copy_phone)
        self.today_edit_phone = QPushButton("Изменить номер")
        self.today_edit_phone.clicked.connect(self.edit_today_phone)
        controls.addWidget(self.today_edit_phone)
        controls.addStretch(1)
        detail_layout.addLayout(controls)
        outer.addWidget(detail)
        self.upcoming_label = QLabel("Ближайшие напоминания")
        self.upcoming_label.setObjectName("sectionTitle")
        outer.addWidget(self.upcoming_label)
        self.upcoming_table = self.create_table(["Когда", "Рейс", "Что сделать", "Водитель / телефон"])
        self.upcoming_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for index, width in ((0, 145), (1, 280), (3, 220)):
            self.upcoming_table.setColumnWidth(index, width)
        self.upcoming_table.itemSelectionChanged.connect(self.on_upcoming_selection)
        outer.addWidget(self.upcoming_table, 2)
        self.pages.addWidget(page)

    def make_routes_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)

        left_panel = QFrame()
        left_panel.setObjectName("surfaceCard")
        splitter.addWidget(left_panel)

        # Right: always-visible actions, then carriers, route info and history.
        details = QFrame()
        details.setObjectName("detailCard")
        box = QVBoxLayout(details)
        box.setContentsMargins(21, 19, 21, 18)
        box.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(12)
        route_identity = QVBoxLayout()
        route_identity.setSpacing(5)
        self.route_action_title = QLabel("КАРТОЧКА РЕЙСА")
        self.route_action_title.setObjectName("eyebrow")
        route_identity.addWidget(self.route_action_title)
        self.route_detail_title = QLabel("Выбери рейс в списке слева")
        self.route_detail_title.setObjectName("routeHeading")
        self.route_detail_title.setWordWrap(True)
        self.route_detail_title.setTextFormat(Qt.TextFormat.PlainText)
        route_identity.addWidget(self.route_detail_title)
        header.addLayout(route_identity, 1)
        self.route_status_badge = QLabel("—")
        self.route_status_badge.setObjectName("routeStatusBadge")
        self.route_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.route_status_badge.setMinimumWidth(95)
        header.addWidget(self.route_status_badge, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(header)
        self.route_subtitle = QLabel("Маршрут, груз и условия выбранного рейса")
        self.route_subtitle.setObjectName("muted")
        self.route_subtitle.setWordWrap(True)
        box.addWidget(self.route_subtitle)
        self.route_data_warning = QLabel('')
        self.route_data_warning.setObjectName('routeDataWarning')
        self.route_data_warning.setWordWrap(True)
        self.route_data_warning.hide()
        box.addWidget(self.route_data_warning)
        self.route_document_label = QLabel("")
        self.route_document_label.setObjectName("documentBadge")
        box.addWidget(self.route_document_label)

        # Four compact information tiles instead of a blank block above the table.
        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.route_metrics = {}
        for key, caption in (("cargo", "ГРУЗ"), ("weight", "ВЕС"),
                             ("places", "МЕСТА"), ("date", "ЗАГРУЗКА"),
                             ("unload", "ВЫГРУЗКА")):
            tile = QFrame()
            tile.setObjectName("metricTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(11, 9, 11, 9)
            tile_layout.setSpacing(3)
            label = QLabel(caption)
            label.setObjectName("metricCaption")
            value = QLabel("—")
            value.setObjectName("metricValue")
            value.setWordWrap(True)
            value.setMinimumHeight(22)
            tile_layout.addWidget(label)
            tile_layout.addWidget(value)
            metrics.addWidget(tile, 1)
            self.route_metrics[key] = value
        box.addLayout(metrics)

        primary_actions = QHBoxLayout()
        primary_actions.setSpacing(9)
        self.route_close_button = QPushButton("Закрыть рейс")
        self.route_close_button.setObjectName("routeClose")
        self.route_close_button.clicked.connect(self.close_selected_route)
        primary_actions.addWidget(self.route_close_button, 1)
        self.route_reopen_button = QPushButton("Вернуть в выложенные")
        self.route_reopen_button.clicked.connect(self.reopen_selected_route)
        primary_actions.addWidget(self.route_reopen_button, 1)
        self.route_doc_button = QPushButton("Жду документы")
        self.route_doc_button.setObjectName("warning")
        self.route_doc_button.clicked.connect(self.toggle_carrier_documents)
        primary_actions.addWidget(self.route_doc_button, 1)
        box.addLayout(primary_actions)

        secondary_actions = QHBoxLayout()
        secondary_actions.setSpacing(9)
        self.route_edit_button = QPushButton("Редактировать рейс")
        self.route_edit_button.clicked.connect(self.edit_route)
        secondary_actions.addWidget(self.route_edit_button, 1)
        self.route_archive_button = QPushButton("В архив")
        self.route_archive_button.clicked.connect(self.toggle_route_archive)
        secondary_actions.addWidget(self.route_archive_button, 1)
        self.route_delete_button = QPushButton("Удалить рейс")
        self.route_delete_button.setObjectName("danger")
        self.route_delete_button.clicked.connect(self.delete_selected_route)
        secondary_actions.addWidget(self.route_delete_button, 1)
        box.addLayout(secondary_actions)
        self.route_restore_button = QPushButton("Восстановить из корзины")
        self.route_restore_button.setObjectName("primary")
        self.route_restore_button.clicked.connect(self.restore_selected_route)
        self.route_restore_button.hide()
        box.addWidget(self.route_restore_button)
        self.route_load_time_button = QPushButton("Назначить загрузку")
        self.route_load_time_button.clicked.connect(self.edit_selected_load_time)
        box.addWidget(self.route_load_time_button)

        self.route_tabs = QTabWidget()
        self.route_tabs.setObjectName("routeTabs")
        carriers_tab = QWidget()
        ct = QVBoxLayout(carriers_tab)
        ct.setContentsMargins(2, 12, 2, 4)
        ct.setSpacing(10)
        self.route_carriers_table = self.create_table(["Перевозчик", "Ставка", "Статус"])
        self.route_carriers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.route_carriers_table.setColumnWidth(1, 110)
        self.route_carriers_table.setColumnWidth(2, 118)
        self.route_carriers_table.verticalHeader().setDefaultSectionSize(68)
        self.route_carriers_table.doubleClicked.connect(self.edit_route_carrier)
        ct.addWidget(self.route_carriers_table, 1)
        cc = QHBoxLayout()
        self.route_add_carrier = QPushButton("+ Машина")
        self.route_add_carrier.clicked.connect(self.add_carrier)
        cc.addWidget(self.route_add_carrier)
        edit_carrier = QPushButton("Изменить")
        edit_carrier.clicked.connect(self.edit_route_carrier)
        cc.addWidget(edit_carrier)
        delete_carrier = QPushButton("Удалить")
        delete_carrier.setObjectName("danger")
        delete_carrier.clicked.connect(self.delete_route_carrier)
        cc.addWidget(delete_carrier)
        ct.addLayout(cc)
        self.route_tabs.addTab(carriers_tab, "Перевозчики")
        self.route_detail_text = QPlainTextEdit()
        self.route_detail_text.setReadOnly(True)
        self.route_detail_text.setObjectName("readOnlyCard")
        self.route_detail_text.setPlaceholderText("Карточка выбранного рейса")
        self.route_tabs.addTab(self.route_detail_text, "Информация")
        self.route_history = QPlainTextEdit()
        self.route_history.setReadOnly(True)
        self.route_history.setObjectName("readOnlyCard")
        self.route_history.setPlaceholderText("История перевозки")
        self.route_tabs.addTab(self.route_history, "История")
        box.addWidget(self.route_tabs, 1)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 11)
        splitter.setStretchFactor(1, 10)
        splitter.setSizes([690, 630])
        outer.addWidget(splitter, 1)
        self.pages.addWidget(page)
        build_trips(self, page, splitter, left_panel, details)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "summary_layout"):
            adapt_trips(self)

    def make_carriers_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        actions = QHBoxLayout()
        self.carrier_search = text_field(placeholder="Поиск: телефон, имя перевозчика, город или ID")
        self.carrier_search.textChanged.connect(self.refresh_carriers)
        actions.addWidget(self.carrier_search, 1)
        add = QPushButton("+ Записать машину")
        add.setObjectName("primary")
        add.clicked.connect(self.add_carrier)
        actions.addWidget(add)
        edit = QPushButton("Редактировать")
        edit.clicked.connect(self.edit_carrier)
        actions.addWidget(edit)
        history = QPushButton("История по телефону")
        history.clicked.connect(self.show_phone_history)
        actions.addWidget(history)
        delete = QPushButton("Удалить машину")
        delete.setObjectName("danger")
        delete.clicked.connect(self.delete_selected_carrier)
        actions.addWidget(delete)
        outer.addLayout(actions)
        self.carriers_table = self.create_table([
            "Рейс", "Перевозчик / телефон", "Машина", "Ставка перевозчика",
            "Предложить заказчику", "Маржа компании", "Моя доля", "Статус",
        ])
        self.carriers_table.doubleClicked.connect(self.edit_carrier)
        self.carriers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index, width in enumerate([280, 190, 120, 160, 180, 150, 125, 145]):
            self.carriers_table.setColumnWidth(index, width)
        self.carriers_table.itemSelectionChanged.connect(self.refresh_pricing_details)
        outer.addWidget(self.carriers_table, 1)
        self.pricing_details = QLabel("Выбери перевозчика, чтобы увидеть подробный расчёт для заказчика.")
        self.pricing_details.setWordWrap(True)
        self.pricing_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pricing_details.setMinimumHeight(90)
        self.pricing_details.setStyleSheet(
            "background: #1b2530; color: #e4ebf2; border: 1px solid #2c3a49; border-radius: 10px; padding: 14px;"
        )
        outer.addWidget(self.pricing_details)
        self.pages.addWidget(page)

    def make_card_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(heading("Карточка рейса для звонка"))
        top = QHBoxLayout()
        self.card_select = RoutePicker()
        self.card_select.setEditable(True)
        self.card_select.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.card_select.lineEdit().setPlaceholderText("Начни вводить маршрут или ID рейса…")
        self.card_select.lineEdit().setClearButtonEnabled(True)
        card_completer = QCompleter(self.card_select.model(), self.card_select)
        card_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        card_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        card_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.card_select.setCompleter(card_completer)
        style_combo_popup(self.card_select)
        self.card_select.currentIndexChanged.connect(self.refresh_card)
        self.card_select.editTextChanged.connect(self.refresh_card)
        top.addWidget(self.card_select, 1)
        copy = QPushButton("Копировать текст")
        copy.setObjectName("primary")
        copy.clicked.connect(self.copy_card)
        top.addWidget(copy)
        outer.addLayout(top)
        self.card_body = text_area(height=400)
        self.card_body.setReadOnly(True)
        self.card_body.setFont(QFont("Segoe UI", 13))
        outer.addWidget(self.card_body, 1)
        self.pages.addWidget(page)

    def selected_route_id(self) -> str | None:
        items = self.routes_table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def selected_carrier_id(self) -> int | None:
        items = self.carriers_table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def add_route(self):
        dialog = RouteDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.save_route(dialog.payload())
                self.refresh_all()
            except Exception as exc:
                log_exception("Сохранение рейса", exc)
                QMessageBox.critical(self, "Ошибка сохранения", str(exc))

    def edit_route(self, *_):
        route_id = self.selected_route_id()
        if not route_id:
            QMessageBox.information(self, "Выбери рейс", "Сначала выдели строку рейса.")
            return
        original = self.db.get_route(route_id)
        if original and original.get("deleted_at"):
            QMessageBox.information(self, "Рейс в корзине", "Сначала восстанови рейс из корзины.")
            return
        if not original:
            QMessageBox.warning(self, "Рейс не найден", "Запись больше не существует.")
            self.refresh_all()
            return
        dialog = RouteDialog(self.db, original, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                changes = dialog.payload()
                changes["id"] = route_id  # Edits must never create a second route.
                self.db.save_route(changes)
                tracking = self.db.tracking(route_id)
                if (changes.get("date_window") != (original.get("date_window") or "")
                        and tracking and tracking["phase"] == "К загрузке" and tracking["load_due_at"]):
                    if localized_question(self, "Перенести напоминания?",
                            "Время загрузки рейса изменено. Перенести напоминания о загрузке?",
                            yes_text="Перенести", no_text="Оставить время"):
                        time_dialog = DateTimeDialog("Новое время загрузки",
                            "Укажи новое предполагаемое время прибытия машины.",
                            tracking["load_due_at"], parent=self)
                        if time_dialog.exec() == QDialog.DialogCode.Accepted:
                            self.db.delay_loading(route_id, time_dialog.value())
                self.refresh_all()
            except Exception as exc:
                log_exception("Редактирование рейса", exc)
                QMessageBox.critical(self, "Ошибка сохранения", str(exc))

    def add_carrier(self):
        if not self.db.routes(include_closed=False):
            QMessageBox.information(self, "Нет открытых рейсов", "Сначала добавь или открой хотя бы один рейс.")
            return
        # Never preselect a stale route from another page while taking a new call.
        preferred = self.selected_route_id() if self.navigation.currentRow() == 1 else None
        dialog = CarrierDialog(self.db, preferred_route=preferred, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.save_carrier(dialog.payload())
                self.refresh_all()
            except Exception as exc:
                log_exception("Сохранение перевозчика", exc)
                QMessageBox.critical(self, "Ошибка сохранения", str(exc))

    def edit_carrier(self, *_):
        carrier_id = self.selected_carrier_id()
        if carrier_id is None:
            QMessageBox.information(self, "Выбери перевозчика", "Сначала выдели строку в журнале.")
            return
        self._edit_carrier_by_id(carrier_id)

    def edit_route_carrier(self, *_):
        items = self.route_carriers_table.selectedItems()
        carrier_id = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        if carrier_id is None:
            QMessageBox.information(self, "Выбери машину", "Выдели перевозчика в карточке рейса.")
            return
        self._edit_carrier_by_id(carrier_id)

    def _edit_carrier_by_id(self, carrier_id: int):
        record = self.db.get_carrier(carrier_id)
        if not record:
            QMessageBox.warning(self, "Машина не найдена", "Запись уже удалена.")
            self.refresh_all()
            return
        dialog = CarrierDialog(self.db, record=record, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.save_carrier(dialog.payload(), carrier_id)
                self.refresh_all()
            except Exception as exc:
                log_exception("Редактирование перевозчика", exc)
                QMessageBox.critical(self, "Ошибка сохранения", str(exc))

    def delete_selected_carrier(self):
        carrier_id = self.selected_carrier_id()
        if carrier_id is None:
            QMessageBox.information(self, "Выбери машину", "Выдели машину, которую нужно удалить.")
            return
        self._delete_carrier_by_id(carrier_id)

    def delete_route_carrier(self):
        items = self.route_carriers_table.selectedItems()
        carrier_id = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        if carrier_id is None:
            QMessageBox.information(self, "Выбери машину", "Выдели перевозчика в карточке рейса.")
            return
        self._delete_carrier_by_id(carrier_id)

    def _delete_carrier_by_id(self, carrier_id: int):
        record = self.db.get_carrier(carrier_id)
        if not record:
            return
        answer = QMessageBox.question(
            self, "Удалить машину?",
            f"Удалить запись «{record.get('carrier') or record.get('phone') or 'без имени'}» "
            f"по рейсу {record['route_id']}?\n\nЭто удалит только выбранную запись, не весь рейс. "
            "Если машина выполняет рейс, сначала верни его в выложенные.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.delete_carrier(carrier_id)
            self.refresh_all()
            self.statusBar().showMessage("Запись машины удалена", 4000)
        except ValueError as exc:
            QMessageBox.warning(self, "Нельзя удалить машину", str(exc))
        except Exception as exc:
            log_exception("Удаление машины", exc)
            QMessageBox.critical(self, "Ошибка удаления", str(exc))

    def delete_selected_route(self):
        route_id = self.selected_route_id()
        route = self.db.get_route(route_id) if route_id else None
        if not route or route.get("deleted_at"):
            return
        tracking = self.db.tracking(route_id)
        active = bool(tracking and tracking["phase"] not in ("Пауза", "Завершён"))
        message = (f"Переместить {route_id} · {route.get('origin') or '?'} → "
                   f"{route.get('destination') or '?'} в корзину?\n\n"
                   "Перевозчики, ставки и история сохранятся. Рейс можно восстановить.")
        if active:
            message += ("\n\nВНИМАНИЕ: сейчас идёт контроль перевозки. "
                        "Невыполненные напоминания будут отменены.")
        if not localized_question(self, "Удалить рейс?", message,
                                  yes_text="В корзину", no_text="Отмена"):
            return
        try:
            self.db.move_route_to_trash(route_id)
            self.refresh_all()
            self.statusBar().showMessage("Рейс перемещён в корзину — его можно восстановить", 6500)
        except Exception as exc:
            log_exception("Удаление рейса", exc)
            QMessageBox.critical(self, "Не удалось удалить рейс", str(exc))

    def restore_selected_route(self):
        route_id = self.selected_route_id()
        route = self.db.get_route(route_id) if route_id else None
        if not route or not route.get("deleted_at"):
            return
        try:
            self.db.restore_route(route_id)
            self.navigation.setCurrentRow(1)
            self.show_closed.setChecked(True)
            self.show_archived.setChecked(True)
            self.refresh_all()
            self.statusBar().showMessage("Рейс восстановлен. Старые напоминания не возобновляются автоматически.", 8000)
        except Exception as exc:
            log_exception("Восстановление рейса", exc)
            QMessageBox.critical(self, "Не удалось восстановить рейс", str(exc))

    @staticmethod
    def document_status(route: dict | None) -> str:
        return "Жду документы" if route and route.get("carrier_docs_pending") else "—"

    def refresh_route_details(self, *_):
        route_id = self.selected_route_id()
        route = self.db.get_route(route_id) if route_id else None
        self.route_carriers_table.blockSignals(True)
        self.route_carriers_table.setRowCount(0)
        self.route_carriers_table.blockSignals(False)
        update_trip_footer(self, route)
        if not route:
            self.route_detail_title.setText("Выбери рейс, чтобы увидеть звонившие машины")
            self.route_status_badge.setText("—")
            self.route_status_badge.setStyleSheet("")
            self.route_subtitle.setText("Маршрут, груз и условия выбранного рейса")
            self.route_data_warning.hide()
            for value in self.route_metrics.values():
                value.setText("—")
            self.route_detail_text.clear()
            self.route_history.clear()
            self.route_document_label.clear()
            for button in (self.route_edit_button, self.route_close_button, self.route_reopen_button,
                           self.route_doc_button, self.route_archive_button, self.route_load_time_button,
                           self.route_delete_button, self.route_restore_button):
                button.setEnabled(False)
            self.route_action_title.setText("Выбери рейс")
            self.route_add_carrier.setEnabled(False)
            self.route_restore_button.hide()
            self.route_delete_button.hide()
            return
        tracking = self.db.tracking(route_id)
        display_fields = trip_display_fields(route)
        self.route_data_warning.setText(display_fields['warning'])
        self.route_data_warning.setVisible(bool(display_fields['warning']))
        status = route.get("status") or "Выложен"
        self.route_detail_title.setText(f"{route.get('origin') or '?'} → {route.get('destination') or '?'}")
        self.route_action_title.setText(f"РЕЙС {route_id}" + (" · АРХИВ" if route["archived"] else ""))
        self.route_status_badge.setText("В корзине" if route.get("deleted_at") else status)
        badge_colors = (
            ("#233e35", "#a0e4bf", "#356c54") if status == "Выложен" else
            ("#472a30", "#ffb8bd", "#815058") if status == "Закрыт" else
            ("#42371f", "#f6d78e", "#765f32")
        )
        self.route_status_badge.setStyleSheet(
            f"background: {badge_colors[0]}; color: {badge_colors[1]}; "
            f"border: 1px solid {badge_colors[2]}; border-radius: 10px; "
            "padding: 7px 12px; font-size: 14px; font-weight: 700;"
        )
        self.route_subtitle.setText(
            " · ".join(part for part in (
                route.get("sender"), display_fields['cargo'] if not display_fields['warning'] else None,
                "В архиве" if route.get("archived") else ""
            ) if part) or "Отправитель и груз не указаны"
        )
        for key, text in (("cargo", display_fields['cargo']),
                          ("weight", display_fields['weight']),
                          ("places", route.get("places") or "—"),
                          ("date", route.get("date_window") or "—"),
                          ("unload", route.get("unload_window") or "—")):
            self.route_metrics[key].setText(str(text))
            self.route_metrics[key].setToolTip(str(text))
        if display_fields['warning']:
            self.route_metrics['weight'].setToolTip(display_fields['warning'])
        doc = self.document_status(route)
        self.route_document_label.setText(doc if doc != "—" else "")
        self.route_document_label.setVisible(doc != "—")
        self.route_document_label.setStyleSheet(
            "color: #e8c478;" if doc == "Жду документы" else "color: #79cba3;"
        )
        detail = card_text(route)
        if tracking and tracking["phase"] != "Пауза":
            phone = tracking.get("driver_phone") or "не указан"
            detail += (f"\n\nКонтроль: {tracking['phase']}\n"
                       f"Водитель: {tracking.get('driver_name') or 'не указан'} · {phone}\n"
                       f"Загрузка: {display_datetime(tracking['load_due_at'])}\n"
                       f"Выгрузка: {display_datetime(tracking['unload_due_at'])}")
        self.route_detail_text.setPlainText(detail)
        history = self.db.route_events(route_id, limit=15)
        self.route_history.setPlainText(
            "История перевозки\n\n" + "\n\n".join(
                f"{display_datetime(e['happened_at'])}\n{e['event']}"
                + (f" · {e['details']}" if e["details"] else "") for e in history
            ) if history else "История перевозки появится после закрытия рейса."
        )
        carriers = self.db.carriers(route_id=route_id)
        self.route_tabs.setTabText(0, f"Перевозчики ({len(carriers)})")
        self.route_carriers_table.blockSignals(True)
        self.route_carriers_table.setRowCount(len(carriers))
        for row, c in enumerate(carriers):
            values = [c.get("carrier") or "—", c.get("phone") or "—",
                      c.get("body") or "—", money(c.get("desired_rate")) or "—",
                      c.get("status") or "—"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, c["id"])
                item.setToolTip(f"{value}\nНа загрузке: {arrival_for_edit(c) or 'не указано'}")
                if col == 4:
                    item.setForeground(QColor(
                        "#79cba3" if value == "Согласован" else
                        "#f08d8d" if value == "Отказ" else
                        "#e8c478" if value in ("Перезвонить", "Думает") else "#dce7f1"
                    ))
                self.route_carriers_table.setItem(row, col, item)
        self.route_carriers_table.blockSignals(False)
        archived = bool(route["archived"])
        self.route_carriers_table.resizeRowsToContents()
        deleted = bool(route.get("deleted_at"))
        self.route_restore_button.setVisible(deleted)
        self.route_restore_button.setEnabled(deleted)
        self.route_delete_button.setVisible(not deleted)
        self.route_delete_button.setEnabled(not deleted)
        self.route_edit_button.setEnabled(not deleted)
        self.route_close_button.setEnabled(status != "Закрыт" and not archived and not deleted)
        self.route_close_button.setVisible(status != "Закрыт" and not archived and not deleted)
        self.route_reopen_button.setEnabled(status == "Закрыт" and not archived and not deleted)
        self.route_reopen_button.setVisible(status == "Закрыт" and not archived and not deleted)
        self.route_doc_button.setEnabled(not archived and not deleted)
        self.route_doc_button.setText("Документы получены" if route["carrier_docs_pending"] else "Жду документы")
        self.route_archive_button.setEnabled(not deleted)
        self.route_archive_button.setText("Вернуть из архива" if archived else "В архив")
        self.route_add_carrier.setEnabled(status != "Закрыт" and not archived and not deleted)
        self.route_load_time_button.setVisible(bool(tracking and tracking["phase"] == "К загрузке" and not archived and not deleted))
        self.route_load_time_button.setEnabled(bool(tracking and tracking["phase"] == "К загрузке" and not archived and not deleted))
        self.route_load_time_button.setText("Перенести загрузку" if tracking and tracking["load_due_at"]
                                            else "Назначить загрузку")

    def toggle_carrier_documents(self):
        route_id = self.selected_route_id()
        route = self.db.get_route(route_id) if route_id else None
        if not route:
            return
        try:
            self.db.set_carrier_documents(route_id, not bool(route["carrier_docs_pending"]))
            self.refresh_all()
        except ValueError as exc:
            QMessageBox.warning(self, "Документы перевозчика", str(exc))

    def toggle_route_archive(self):
        route_id = self.selected_route_id()
        route = self.db.get_route(route_id) if route_id else None
        if not route:
            return
        archive = not bool(route["archived"])
        if archive and not localized_question(self, "Переместить рейс в архив?",
                "Рейс исчезнет из рабочего списка, но все машины, ставки и история сохранятся. "
                "Вернуть его можно в разделе «Архив».",
                yes_text="В архив", no_text="Отмена"):
            return
        try:
            self.db.archive_route(route_id, archive=archive)
            self.refresh_all()
            self.statusBar().showMessage("Рейс перемещён в архив" if archive
                                         else "Рейс возвращён из архива", 5000)
        except ValueError as exc:
            QMessageBox.warning(self, "Архив", str(exc))

    def edit_selected_load_time(self):
        route_id = self.selected_route_id()
        tracking = self.db.tracking(route_id) if route_id else None
        if not tracking or tracking["phase"] != "К загрузке":
            return
        dialog = DateTimeDialog("Время загрузки", "Когда водитель должен прибыть на загрузку?",
                                tracking["load_due_at"], parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.db.delay_loading(route_id, dialog.value())
            self.refresh_all()
            self.refresh_today()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось назначить загрузку", str(exc))

    def close_selected_route(self):
        route_id = self.selected_route_id()
        route = self.db.get_route(route_id) if route_id else None
        if not route:
            QMessageBox.information(self, "Выбери рейс", "Выдели рейс, который согласовал.")
            return
        if route["status"] == "Закрыт":
            QMessageBox.information(self, "Рейс уже закрыт", "Контроль этого рейса уже включён.")
            return
        carriers = self.db.carriers(route_id=route_id)
        if not carriers:
            QMessageBox.information(self, "Нет машин", "Сначала запиши перевозчика по этому рейсу.")
            return
        items = self.route_carriers_table.selectedItems()
        preferred = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        dialog = CloseRouteDialog(route, carriers, preferred_id=preferred, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.db.close_route(route_id, **dialog.values())
            # A freshly closed route must not disappear from under the user's cursor.
            self.show_closed.setChecked(True)
            self.refresh_all()
            if dialog.values()["load_due_at"]:
                self.statusBar().showMessage("Рейс закрыт. Контроль и напоминания включены.", 6000)
            else:
                self.statusBar().showMessage("Рейс закрыт. Укажи время загрузки, чтобы включить напоминания.", 9000)
        except Exception as exc:
            log_exception("Закрытие рейса", exc)
            QMessageBox.critical(self, "Не удалось закрыть рейс", str(exc))

    def reopen_selected_route(self):
        route_id = self.selected_route_id()
        if not route_id:
            return
        answer = QMessageBox.question(
            self, "Вернуть рейс в выложенные?",
            "Рейс снова станет доступен для поиска машины. "
            "Невыполненные напоминания по текущей перевозке будут отменены. "
            "История останется в базе. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.db.reopen_route(route_id)
            self.refresh_all()
        except Exception as exc:
            log_exception("Возврат рейса", exc)
            QMessageBox.critical(self, "Ошибка", str(exc))

    def _selected_task_id(self) -> int | None:
        for table in (self.today_table, self.upcoming_table):
            items = table.selectedItems()
            if items:
                return items[0].data(Qt.ItemDataRole.UserRole)
        return None

    def _selected_task(self) -> dict | None:
        reminder_id = self._selected_task_id()
        if reminder_id is None:
            return None
        return next((r for r in self.db.reminder_rows() if r["id"] == reminder_id), None)

    def on_today_selection(self):
        if self.today_table.selectedItems():
            self.upcoming_table.blockSignals(True)
            self.upcoming_table.clearSelection()
            self.upcoming_table.blockSignals(False)
        self.refresh_today_detail()

    def on_upcoming_selection(self):
        if self.upcoming_table.selectedItems():
            self.today_table.blockSignals(True)
            self.today_table.clearSelection()
            self.today_table.blockSignals(False)
        self.refresh_today_detail()

    def _fill_task_table(self, table: QTableWidget, tasks: list[dict], *, show_state: bool, selected_id):
        table.blockSignals(True)
        table.setRowCount(len(tasks))
        current = datetime.now().isoformat(timespec="minutes")
        selected_row = None
        for row, task in enumerate(tasks):
            phone = task["contact_phone"] or "номер не указан"
            who = task["driver_name"] or task["carrier"] or "Без имени"
            state = "Просрочено" if task["due_at"] < current else "Сегодня"
            values = [display_datetime(task["due_at"]), task["route_label"], task["title"],
                      f"{who} · {phone}"] + ([state] if show_state else [])
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, task["id"])
                item.setToolTip(value)
                if show_state and col == 4:
                    item.setForeground(QColor("#f08d8d" if state == "Просрочено" else "#e8c478"))
                table.setItem(row, col, item)
            if task["id"] == selected_id:
                selected_row = row
        if selected_row is not None:
            table.selectRow(selected_row)
        table.blockSignals(False)
        return selected_row is not None

    def refresh_today(self, *_):
        selected_id = self._selected_task_id()
        all_tasks = self.db.reminder_rows()
        now = datetime.now()
        today_end = now.strftime("%Y-%m-%dT23:59")
        today = [r for r in all_tasks if r["due_at"] <= today_end]
        future_limit = (now.replace(hour=23, minute=59, second=0, microsecond=0)
                        + timedelta(days=7)).isoformat(timespec="minutes")
        future = [r for r in all_tasks if today_end < r["due_at"] <= future_limit]
        self.today_title.setText(f"Сегодня · {len(today)} задач")
        found = self._fill_task_table(self.today_table, today, show_state=True, selected_id=selected_id)
        found = self._fill_task_table(self.upcoming_table, future, show_state=False, selected_id=selected_id) or found
        if not found:
            if today:
                self.today_table.selectRow(0)
            elif future:
                self.upcoming_table.selectRow(0)
        self.upcoming_label.setText(f"Ближайшие 7 дней · {len(future)} задач")
        self.refresh_today_detail()

    def refresh_today_detail(self):
        task = self._selected_task()
        for button in (self.today_action_button, self.today_snooze_button,
                       self.today_change_button, self.today_copy_phone, self.today_edit_phone):
            button.setEnabled(task is not None)
        if task is None:
            self.today_detail.setText("Нет выбранного напоминания. Если список пуст, срочных задач пока нет.")
            return
        phone_kind = "Номер водителя" if task["phone_is_driver"] else "Номер перевозчика (водитель не указан)"
        phone = task["contact_phone"] or "Номер не указан — уточни у перевозчика"
        self.today_detail.setText(
            f"{task['route_label']}\n{task['title']} · {display_datetime(task['due_at'])}\n"
            f"{task['driver_name'] or task['carrier'] or 'Без имени'} · {phone_kind}: {phone}"
        )
        names = {
            "location_load": "Звонок выполнен", "loading": "Подтвердить загрузку",
            "photos": "Фото получены", "unload_eta": "Указать время выгрузки",
            "location_unload": "Звонок выполнен", "unloading": "Подтвердить выгрузку",
            "signed_docs": "Документы получены",
        }
        self.today_action_button.setText(names.get(task["kind"], "Подтвердить выполнение"))
        self.today_change_button.setText(
            "Водитель задерживается" if task["kind"] in ("location_load", "loading") else
            "Изменить время выгрузки" if task["kind"] in ("location_unload", "unloading") else
            "Изменить время"
        )
        self.today_copy_phone.setEnabled(bool(task["contact_phone"]))

    def perform_today_action(self):
        task = self._selected_task()
        if not task:
            return
        kind, route_id = task["kind"], task["route_id"]
        try:
            if kind in ("location_load", "location_unload"):
                self.db.complete_reminder(task["id"])
            elif kind == "loading":
                answer = QMessageBox.question(
                    self, "Подтвердить загрузку", "Водитель действительно загрузился?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                unload = None
                if QMessageBox.question(
                    self, "Время выгрузки", "Указать примерную дату и время выгрузки сейчас?\n"
                    "Если пока неизвестно, программа напомнит уточнить позже.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                    dialog = DateTimeDialog("Выгрузка", "Когда примерно водитель должен выгрузиться?", parent=self)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        unload = dialog.value()
                self.db.confirm_loaded(route_id, unload)
            elif kind == "photos":
                self.db.receive_photos(route_id)
            elif kind == "unload_eta":
                dialog = DateTimeDialog("Выгрузка", "Укажи ожидаемые дату и время выгрузки.", parent=self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                self.db.set_unload_eta(route_id, dialog.value())
            elif kind == "unloading":
                answer = QMessageBox.question(
                    self, "Подтвердить выгрузку", "Водитель действительно выгрузился?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self.db.confirm_unloaded(route_id)
            elif kind == "signed_docs":
                self.db.receive_signed_docs(route_id)
            self.refresh_all()
        except Exception as exc:
            log_exception("Обработка напоминания", exc)
            QMessageBox.warning(self, "Не удалось обновить этап", str(exc))

    def snooze_today(self):
        task = self._selected_task()
        if not task:
            return
        try:
            self.db.snooze_reminder(task["id"], minutes=30)
            self.refresh_all()
        except ValueError as exc:
            QMessageBox.warning(self, "Нельзя отложить", str(exc))

    def change_today_time(self):
        task = self._selected_task()
        if not task:
            return
        kind, route_id = task["kind"], task["route_id"]
        tracking = self.db.tracking(route_id)
        if kind in ("location_load", "loading"):
            caption = "Новое время прибытия на загрузку. Связанные напоминания перенесутся вместе."
            initial = tracking["load_due_at"] if tracking else None
        elif kind in ("location_unload", "unloading"):
            caption = "Новое время выгрузки. Связанные напоминания перенесутся вместе."
            initial = tracking["unload_due_at"] if tracking else None
        else:
            caption = "Когда снова напомнить об этой задаче?"
            initial = task["due_at"]
        dialog = DateTimeDialog("Изменить время", caption, initial, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if kind in ("location_load", "loading"):
                self.db.delay_loading(route_id, dialog.value())
            elif kind in ("location_unload", "unloading"):
                self.db.set_unload_eta(route_id, dialog.value())
            else:
                self.db.reschedule_reminder(task["id"], dialog.value())
            self.refresh_all()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось перенести", str(exc))

    def copy_today_phone(self):
        task = self._selected_task()
        if task and task["contact_phone"]:
            QApplication.clipboard().setText(task["contact_phone"])
            self.statusBar().showMessage("Номер скопирован", 3500)

    def edit_today_phone(self):
        task = self._selected_task()
        if not task:
            return
        tracking = self.db.tracking(task["route_id"])
        if not tracking:
            return
        input_dialog = QInputDialog(self)
        input_dialog.setWindowTitle("Номер водителя")
        input_dialog.setLabelText("Телефон водителя (оставь пустым для номера перевозчика):")
        input_dialog.setInputMode(QInputDialog.InputMode.TextInput)
        input_dialog.setTextEchoMode(QLineEdit.EchoMode.Normal)
        input_dialog.setTextValue(tracking.get("driver_phone") or "")
        input_dialog.setOkButtonText("Сохранить")
        input_dialog.setCancelButtonText("Отмена")
        if input_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        phone = input_dialog.textValue()
        try:
            self.db.set_driver_phone(task["route_id"], phone)
            self.refresh_all()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось изменить номер", str(exc))

    def check_updates(self, *, manual: bool = False):
        if self._update_checking or self._update_downloading:
            if manual:
                self.statusBar().showMessage("Проверка обновлений уже выполняется", 3000)
            return
        if not update_manifest_url():
            if manual:
                QMessageBox.information(self, "Обновления", "Канал обновлений ещё не настроен.")
            return
        self._update_checking = True
        if manual:
            self.statusBar().showMessage("Проверяю обновления…")

        def worker():
            try:
                manifest = newer_manifest()
            except UpdateError as exc:
                self.update_check_failed.emit(str(exc), manual)
            except Exception:
                self.update_check_failed.emit("Не удалось проверить обновления", manual)
            else:
                self.update_checked.emit(manifest, manual)

        threading.Thread(target=worker, name="LogistUpdateCheck", daemon=True).start()

    def _on_update_check_failed(self, message: str, manual: bool):
        self._update_checking = False
        self.statusBar().clearMessage()
        if manual:
            QMessageBox.warning(self, "Обновления", message)

    def _on_update_checked(self, manifest: object, manual: bool):
        self._update_checking = False
        self.statusBar().clearMessage()
        if not manifest:
            if manual:
                QMessageBox.information(self, "Обновления", f"Установлена актуальная версия {APP_VERSION}.")
            return
        manifest = dict(manifest)
        notes = "\n".join(f"• {line}" for line in manifest.get("notes", []))
        text = f"Доступна версия {manifest['version']}." + (f"\n\n{notes}" if notes else "")
        answer = QMessageBox.question(
            self, "Обновление LogistDesk", text + "\n\nУстановить сейчас?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            self._download_update(manifest)

    def _download_update(self, manifest: dict):
        if self._update_downloading:
            return
        self._update_downloading = True
        self.statusBar().showMessage(f"Скачиваю LogistDesk {manifest['version']}…")

        def worker():
            try:
                package = download_package(manifest)
            except UpdateError as exc:
                self.update_download_failed.emit(str(exc))
            except Exception:
                self.update_download_failed.emit("Не удалось скачать обновление")
            else:
                self.update_downloaded.emit(package, manifest)

        threading.Thread(target=worker, name="LogistUpdateDownload", daemon=True).start()

    def _on_update_download_failed(self, message: str):
        self._update_downloading = False
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "Обновление не установлено", message)

    def _on_update_downloaded(self, package: object, manifest: object):
        self._update_downloading = False
        self.statusBar().showMessage("Запускаю обновление…")
        try:
            launch_updater(Path(package), dict(manifest))
        except UpdateError as exc:
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "Обновление не установлено", str(exc))
            return
        self._really_quit = True
        self.close()
        QApplication.instance().quit()

    def show_settings(self):
        AutoStartDialog(Path(__file__).resolve().parent, parent=self).exec()

    def setup_tray(self):
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self._tray = None
        if not self._tray_available:
            self.statusBar().showMessage(
                "Системный трей недоступен: напоминания видны в «Сегодня», пока окно открыто.", 9000)
            return
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip("LogistDesk · контроль рейсов")
        menu = QMenu(self)
        open_action = menu.addAction("Открыть LogistDesk")
        open_action.triggered.connect(self.show_from_tray)
        menu.addSeparator()
        exit_action = menu.addAction("Выход · остановить напоминания")
        exit_action.triggered.connect(self.quit_from_tray)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self.tray_activated)
        self._tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_from_tray()

    def show_from_tray(self):
        if self.vault is not None and self._security_locked:
            dialog = LoginDialog(self.vault, unlock_only=True)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self._security_locked = False
            self._last_interaction = time.monotonic()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.navigation.setCurrentRow(0)
        self.refresh_today()

    def quit_from_tray(self):
        self._really_quit = True
        self.close()
        QApplication.instance().quit()

    def poll_reminders(self):
        try:
            due = self.db.reminder_rows(due_only=True)
            self.refresh_today()
            unseen = [r for r in due if self._shown_due.get(r["id"]) != r["due_at"]]
            if not unseen:
                return
            for task in unseen:
                self._shown_due[task["id"]] = task["due_at"]
            first = unseen[0]
            phone_kind = "Водитель" if first["phone_is_driver"] else "Перевозчик"
            phone = first["contact_phone"] or "номер не указан"
            extra = f"\nЕщё напоминаний: {len(unseen) - 1}" if len(unseen) > 1 else ""
            # Phone first: Windows may truncate long toast bodies.
            if self.vault is not None or self._security_locked:
                # Windows can retain previous toasts in notification history.
                # Keep secure-mode notifications generic even while unlocked.
                message = "Есть новое напоминание. Открой LogistDesk, чтобы увидеть подробности."
            else:
                message = (f"{phone_kind}: {first['driver_name'] or first['carrier'] or 'без имени'} · {phone}\n"
                           f"{first['route_id']} · {first['origin']} → {first['destination']}\n"
                           f"{first['title']}{extra}")
            if self._tray:
                self._tray.showMessage("LogistDesk · пора связаться с водителем", message,
                                       QSystemTrayIcon.MessageIcon.Information, 12000)
            self.statusBar().showMessage("Есть напоминания: открой раздел «Сегодня»", 10000)
        except Exception as exc:
            log_exception("Проверка напоминаний", exc)

    def refresh_routes(self, *_):
        previous = self.selected_route_id()
        categories = refresh_summary(self)
        routes = self.db.routes(self.route_search.text(),
                                include_closed=self.show_closed.isChecked() or self.deleted_only or self.archive_only,
                                include_archived=self.show_archived.isChecked() or self.archive_only or self.route_filter == "archive",
                                deleted_only=self.deleted_only)
        if self.archive_only:
            routes = [route for route in routes if route["archived"]]
        if not self.archive_only and not self.deleted_only and self.route_filter != "all":
            routes = [r for r in routes if self.route_filter in categories[r["id"]]]
        caption = self.summary_buttons[self.route_filter][1]
        if self.archive_only or self.deleted_only:
            caption = "Архив" if self.archive_only else "Корзина"
        self.route_count_label.setText(f"{caption} · {len(routes)}" if routes else "Рейсы не найдены")
        self.routes_table.blockSignals(True)
        self.routes_table.setRowCount(len(routes))
        selected_row = None
        for row, r in enumerate(routes):
            status = r.get("status") or "Выложен"
            if self.deleted_only:
                status = "В корзине"
            elif r["archived"]:
                status += " · Архив"
            display_fields = trip_display_fields(r)
            weight = display_fields['weight']
            cargo = display_fields['cargo'] if display_fields['cargo'] != '—' else r.get('sender') or '—'
            route_text = f"{r.get('origin') or '?'} → {r.get('destination') or '?'}"
            if r.get("carrier_docs_pending"):
                status += "\nЖду документы"
            values = [r["id"], route_text, cargo, str(weight), r.get("date_window") or "—", status]
            for col, value in enumerate(values):
                item = QTableWidgetItem('' if col == 5 else value)
                item.setData(Qt.ItemDataRole.UserRole, r["id"])
                item.setToolTip(route_label(r) + "\n" + (r.get("sender") or "") + "\n"
                                + (r.get("cargo") or "") + "\n" + display_fields['warning'])
                self.routes_table.setItem(row, col, item)
            self.routes_table.setCellWidget(row, 5, status_chips(r, deleted_only=self.deleted_only))
            if r["id"] == previous:
                selected_row = row
        if selected_row is not None:
            self.routes_table.selectRow(selected_row)
        elif routes:
            self.routes_table.selectRow(0)
        self.routes_table.blockSignals(False)
        self.routes_table.resizeRowsToContents()
        for row, r in enumerate(routes):
            badges = route_status_parts(r, deleted_only=self.deleted_only)
            self.routes_table.setRowHeight(row, max(self.routes_table.rowHeight(row), 68 if len(badges) > 1 else 56))
        update_route_columns(self)
        self.refresh_route_details()
        self.route_open_button.setEnabled(self.selected_route_id() is not None)
        if not routes and self._trips_compact_detail:
            self._trips_compact_detail = False
            adapt_trips(self)

    def refresh_carriers(self, *_):
        carriers = self.db.carriers(self.carrier_search.text())
        self.carriers_table.blockSignals(True)
        self.carriers_table.setRowCount(len(carriers))
        for row, r in enumerate(carriers):
            pricing = quote_calculation(r)
            preview = not pricing["confirmed"]
            margin = pricing["company_margin"]
            share = pricing["personal_share"]
            name_phone = " · ".join(x for x in (r["carrier"], r["phone"]) if x) or "—"
            items = [
                r["route_label"], name_phone, r["body"], money(r["desired_rate"]),
                money(pricing["quote"]),
                ("≈ " if preview else "") + money(margin) if margin is not None else "—",
                ("≈ " if preview else "") + money_precise(share) if share is not None else "—",
                r["status"],
            ]
            for col, value in enumerate(items):
                item = QTableWidgetItem(value or "")
                item.setData(Qt.ItemDataRole.UserRole, r["id"])
                item.setToolTip(str(value or ""))
                if col == 5 and margin is not None and margin < 0:
                    item.setForeground(QColor("#f08d8d"))
                if col in (5, 6):
                    tip = "Предварительный расчёт: заказчик ещё не согласовал ставку." if preview else "Ставка заказчика подтверждена."
                    if pricing["vat_warning"]:
                        tip += " " + pricing["vat_warning"]
                    item.setToolTip(tip)
                if col == 7:
                    item.setForeground(QColor(
                        "#79cba3" if value == "Согласован" else
                        "#f08d8d" if value == "Отказ" else
                        "#e8c478" if value in ("Перезвонить", "Думает") else "#dce7f1"
                    ))
                if col == 7 and r["callback_date"] and r["status"] in ("Перезвонить", "Думает"):
                    callback_day = str(r["callback_date"]).strip()
                    if len(callback_day) >= 10 and callback_day[:10] <= date.today().isoformat():
                        item.setBackground(QColor("#665027"))
                self.carriers_table.setItem(row, col, item)
        self.carriers_table.blockSignals(False)
        self.refresh_pricing_details()

    def refresh_pricing_details(self):
        carrier_id = self.selected_carrier_id()
        if carrier_id is None:
            self.pricing_details.setText("Выбери перевозчика, чтобы увидеть подробный расчёт для заказчика.")
            return
        record = self.db.get_carrier(carrier_id)
        if not record:
            return
        route = self.db.get_route(record["route_id"]) or {}
        pricing = quote_calculation(record)
        customer_note = (
            f"Подтверждено заказчиком: {money(pricing['agreed_rate'])}." if pricing["confirmed"]
            else "Заказчик отказался; выплаты по предложению нет." if pricing["customer_status"] == "Отказ"
            else "Маржа и твоя доля пока предварительные."
        )
        lines = [
            f"На ATI: {money(route.get('with_vat')) or '—'} (это не ставка заказчика). "
            f"Перевозчик просит: {money(pricing['requested_rate']) or '—'}. "
            f"Предложить заказчику: {money(pricing['quote']) or '—'}.",
            f"Согласование: {pricing['customer_status']}. " + customer_note,
        ]
        if pricing["company_margin"] is not None:
            lines.append(
                f"Маржа компании: {money(pricing['company_margin'])}; "
                f"твоя доля ({pricing['personal_percent']}%): {money_precise(pricing['personal_share'])}."
            )
        if pricing["vat_warning"]:
            lines.append(pricing["vat_warning"])
        arrival = arrival_for_edit(record) or "не указано"
        etrn = record.get("etrn") or "не уточнил"
        operator = (" · оператор: " + record["etrn_provider"]) if etrn == "Да" and record.get("etrn_provider") else ""
        lines.append(
            f"Контакт: {record.get('carrier') or '—'} · {record.get('phone') or '—'}. "
            f"Машина: {record.get('body') or 'не уточнена'}. "
            f"На загрузке: {arrival}. ЭТрН: {etrn}{operator}."
        )
        lines.append("Условия оплаты озвучены." if record.get("payment_terms_communicated") else
                     "Напомни об оплате: по оригиналам, 10–15 б.д.")
        if record.get("driver_phone"):
            lines.append(f"Водитель: {record.get('driver_name') or 'имя не указано'} · {record['driver_phone']}.")
        if record.get("callback_date"):
            lines.append(f"Перезвонить: {record['callback_date']}.")
        self.pricing_details.setText("\n".join(lines))

    def refresh_choices(self):
        previous = self.card_select.currentData()
        self.card_select.blockSignals(True)
        self.card_select.clear()
        for r in self.db.routes(include_closed=False):
            self.card_select.addItem(route_label(r), r["id"])
        idx = self.card_select.findData(previous)
        if idx >= 0:
            self.card_select.setCurrentIndex(idx)
        self.card_select.blockSignals(False)
        self.refresh_card()

    def refresh_card(self, *_):
        route = self.db.get_route(self.card_select.currentData()) if self.card_select.currentData() else None
        self.card_body.setPlainText(card_text(route) if route else "Пока нет открытых рейсов.")

    def copy_card(self):
        content = self.card_body.toPlainText()
        if content and content != "Пока нет открытых рейсов.":
            QApplication.clipboard().setText(content)
            self.statusBar().showMessage("Карточка рейса скопирована", 3500)

    def open_selected_card(self):
        route_id = self.selected_route_id()
        if not route_id:
            QMessageBox.information(self, "Выбери рейс", "Сначала выдели строку рейса.")
            return
        idx = self.card_select.findData(route_id)
        if idx >= 0:
            self.card_select.setCurrentIndex(idx)
            self.navigation.setCurrentRow(3)
        else:
            QMessageBox.information(self, "Рейс закрыт", "Карточка доступна для открытых рейсов. Измени статус рейса.")

    def refresh_all(self):
        self.refresh_routes()
        self.refresh_carriers()
        self.refresh_choices()
        self.refresh_today()

    def import_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Выбери актуальную Excel-таблицу", str(Path.home()), "Excel (*.xlsx)")
        if not filename:
            return
        try:
            result = import_excel(self.db, filename)
            self.refresh_all()
            QMessageBox.information(
                self, "Импорт завершён",
                f"Новых рейсов: {result['routes_new']}\nНовых записей машин: {result['carriers_new']}\n"
                f"Пропущено существующих рейсов: {result['routes_skipped']}\n"
                f"Пропущено повторных записей машин: {result['carriers_skipped']}\n\n"
                "Существующие записи в приложении не перезаписывались. Исходный Excel не изменён.",
            )
        except Exception as exc:
            log_exception("Импорт Excel", exc)
            QMessageBox.critical(self, "Ошибка импорта", f"{exc}\n\nЖурнал: {log_directory()}")

    def show_phone_history(self):
        carrier_id = self.selected_carrier_id()
        if carrier_id is None:
            QMessageBox.information(self, "История", "Выдели перевозчика в журнале.")
            return
        current = self.db.get_carrier(carrier_id)
        previous = self.db.phone_history(current.get("phone"), exclude_id=carrier_id)
        if not previous:
            QMessageBox.information(self, "История", "Других записей с этим телефоном пока нет.")
            return
        lines = []
        for item in previous:
            route = self.db.get_route(item["route_id"])
            label = route_label(route) if route else item["route_id"]
            lines.append(f"{item['call_date'] or 'Дата не указана'} | {label}\n"
                         f"Статус: {item['status']} | Ставка: {money(item['desired_rate']) or '—'}\n"
                         f"{item['comment'] or ''}")
        dialog = QDialog(self)
        dialog.setWindowTitle(f"История звонков: {current.get('phone') or 'без телефона'}")
        dialog.resize(790, 500)
        layout = QVBoxLayout(dialog)
        viewer = text_area("\n\n──────────\n\n".join(lines), height=390)
        viewer.setReadOnly(True)
        layout.addWidget(viewer)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def export_file(self):
        if self.vault is not None and not localized_question(
                self, "Незашифрованная выгрузка",
                "CSV-файлы НЕ будут зашифрованы. Другие пользователи смогут их прочитать, "
                "если получат доступ к папке. Продолжить?", yes_text="Выгрузить"):
            return
        folder = QFileDialog.getExistingDirectory(self, "Папка для выгрузки CSV", str(Path.home()))
        if not folder:
            return
        try:
            files = self.db.export_csv(folder)
            QMessageBox.information(self, "Выгрузка готова", "Созданы файлы:\n" + "\n".join(map(str, files)) +
                                    "\n\nЕсли файлы с такими именами уже были, они заменены.")
        except Exception as exc:
            log_exception("Выгрузка CSV", exc)
            QMessageBox.critical(self, "Ошибка выгрузки", f"{exc}\n\nЖурнал: {log_directory()}")

    def backup(self):
        try:
            path = self.db.backup()
            QMessageBox.information(self, "Копия сохранена", f"Резервная копия базы:\n{path}")
        except Exception as exc:
            log_exception("Резервное копирование", exc)
            QMessageBox.critical(self, "Ошибка", f"{exc}\n\nЖурнал: {log_directory()}")

    def closeEvent(self, event):
        if self._tray_available and not self._really_quit:
            self._lock_app()
            self.hide()
            event.ignore()
            if self._tray and not self._tray_notice_shown:
                self._tray.showMessage("LogistDesk работает в фоне",
                                       "Напоминания активны. Открой приложение через значок возле часов. "
                                       "Для полного выхода используй меню значка.",
                                       QSystemTrayIcon.MessageIcon.Information, 8000)
                self._tray_notice_shown = True
            return
        self.reminder_timer.stop()
        if self.vault is not None:
            self._security_timer.stop()
            QApplication.instance().removeEventFilter(self)
            if self._session_registered and os.name == "nt":
                try:
                    import ctypes
                    from ctypes import wintypes
                    unregister = ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification
                    unregister.argtypes = [wintypes.HWND]
                    unregister.restype = wintypes.BOOL
                    unregister(int(self.winId()))
                except (AttributeError, OSError):
                    pass
        if self._tray:
            self._tray.hide()
        self.db.close()
        super().closeEvent(event)


def main():
    set_windows_app_id()
    configure_logging()
    install_exception_hook()
    app = QApplication(sys.argv)
    app.setApplicationName("LogistDesk")
    app.setApplicationDisplayName("LogistDesk")
    app.setOrganizationName("LogistDesk")
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    QLocale.setDefault(QLocale(QLocale.Language.Russian, QLocale.Country.Russia))
    translator = QTranslator(app)
    if translator.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    apply_dark_palette(app)
    app.setStyleSheet(STYLESHEET)
    vault = SecurityVault(default_data_dir())
    app.aboutToQuit.connect(vault.release_lock)
    start_locked = vault.configured and "--minimized" in sys.argv and QSystemTrayIcon.isSystemTrayAvailable()
    if not start_locked:
        try:
            vault.acquire_lock()
        except VaultError as exc:
            QMessageBox.warning(None, "LogistDesk уже запущен", str(exc))
            return 1
    if not vault.configured:
        if CreateAccountDialog(vault).exec() != QDialog.DialogCode.Accepted:
            vault.release_lock()
            return 0
    elif start_locked:
        # A password-encrypted database cannot send reminders before the first
        # login after a Windows restart. Start in a LOCKED tray state instead.
        locked_tray = QSystemTrayIcon(app_icon(), app)
        locked_tray.setToolTip("LogistDesk · вход необходим для напоминаний")
        locked_menu = QMenu()
        unlock_action = locked_menu.addAction("Войти в LogistDesk")
        locked_menu.addSeparator()
        quit_action = locked_menu.addAction("Выход")
        quit_action.triggered.connect(app.quit)
        locked_tray.setContextMenu(locked_menu)
        def unlock_from_tray():
            try:
                vault.acquire_lock()
            except VaultError as exc:
                QMessageBox.warning(None, "LogistDesk уже запущен", str(exc))
                return
            if LoginDialog(vault).exec() != QDialog.DialogCode.Accepted:
                vault.release_lock()
                return
            if not vault.pin_configured:
                if PinSetupDialog(vault).exec() != QDialog.DialogCode.Accepted:
                    vault.release_lock()
                    return
            try:
                window = LogistWindow(vault=vault)
            except Exception as exc:
                QMessageBox.critical(None, "Не удалось открыть базу", str(exc))
                vault.release_lock()
                return
            app._logist_window = window
            locked_tray.hide()
            window.show()
        unlock_action.triggered.connect(unlock_from_tray)
        locked_tray.activated.connect(lambda reason: unlock_from_tray() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        locked_tray.show()
        return app.exec()
    elif vault._key is None:
        if LoginDialog(vault).exec() != QDialog.DialogCode.Accepted:
            vault.release_lock()
            return 0
        if not vault.pin_configured:
            if PinSetupDialog(vault).exec() != QDialog.DialogCode.Accepted:
                vault.release_lock()
                return 0
    try:
        window = LogistWindow(vault=vault)
    except Exception as exc:
        QMessageBox.critical(None, "Не удалось открыть базу", str(exc))
        vault.release_lock()
        return 1
    if "--minimized" in sys.argv and window._tray_available:
        window._lock_app()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
