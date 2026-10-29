"""Экспериментальная точка входа LogistDesk 1.2.

Рабочая версия 1.1.3 не меняется. Справочник подключается как расширение
к существующему окну, без переписывания уже работающих страниц.
"""
from __future__ import annotations

import sys
import os
import uuid
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QEvent, QTimer
import app as stable_app
from partners_ui import RegistryPage
from route_completion import finish_after_unloading
from PySide6.QtWidgets import (QPushButton, QCompleter, QScrollArea, QSplitter, QFormLayout,
                                 QFrame, QToolButton, QMenu, QLineEdit, QVBoxLayout, QWidget, QComboBox,
                                 QHBoxLayout, QLabel)
from call_bridge import register_call
from cities import setup_city_completers
from readable_popup import make_popup_readable
from draft_ui import DraftController
from drafts import DraftStore
from input_formatting import bind_date, bind_phone
from today_active import ActiveTripsPanel


class LogistWindow12(stable_app.LogistWindow):
    def __init__(self, vault=None):
        super().__init__(vault=vault)
        self._active_trips = ActiveTripsPanel(self.db, self.refresh_all, self)
        self.pages.widget(0).layout().insertWidget(1, self._active_trips)
        self._active_trips.refresh()
        self._draft_windows = {}
        # Track the actual central-widget geometry; it can be laid out *after*
        # the main window receives its resize event when starting maximized.
        self._draft_host = self.centralWidget()
        self._draft_host.installEventFilter(self)
        self._draft_bar = QFrame(self._draft_host)
        self._draft_bar.setObjectName("savedDraftBar")
        self._draft_bar.setStyleSheet(
            "QFrame#savedDraftBar {background:#25394b; border:1px solid #60788e; "
            "border-radius:10px;} QPushButton {text-align:left; padding:7px;} "
            "QScrollArea {background:transparent; border:0;}")
        bar_layout = QVBoxLayout(self._draft_bar)
        bar_layout.setContentsMargins(9, 8, 9, 8)
        bar_layout.setSpacing(4)
        self._draft_title = QLabel("Черновики рейсов", self._draft_bar)
        self._draft_title.setObjectName("sectionTitle")
        bar_layout.addWidget(self._draft_title)
        self._draft_scroll = QScrollArea(self._draft_bar)
        self._draft_scroll.setWidgetResizable(True)
        self._draft_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._draft_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._draft_list = QWidget()
        self._draft_list_layout = QVBoxLayout(self._draft_list)
        self._draft_list_layout.setContentsMargins(0, 0, 0, 0)
        self._draft_list_layout.setSpacing(3)
        self._draft_scroll.setWidget(self._draft_list)
        bar_layout.addWidget(self._draft_scroll)
        self._draft_rows_count = 0
        self._refresh_draft_bar()
        self.partner_page = RegistryPage(self.db, parent=self)
        self.pages.addWidget(self.partner_page)
        original_save_carrier = self.db.save_carrier

        def save_and_index_carrier(record, *args, **kwargs):
            carrier_id = original_save_carrier(record, *args, **kwargs)
            try:
                partner_id = register_call(self.partner_page.registry, dict(record), carrier_id)
                if partner_id is not None:
                    chosen_driver = record.get("selected_driver_id")
                    chosen_vehicle = record.get("selected_vehicle_id")
                    if chosen_driver is not None or chosen_vehicle is not None:
                        self.partner_page.registry.link_call_resources(
                            carrier_id, partner_id, chosen_driver, chosen_vehicle)
            except Exception as exc:
                stable_app.log_exception("Справочник перевозчиков", exc)
            return carrier_id

        self.db.save_carrier = save_and_index_carrier
        original_save_route = self.db.save_route

        def save_and_link_route(record, *args, **kwargs):
            route_id = original_save_route(record, *args, **kwargs)
            if "customer_partner_id" in record:
                partner_id = record.get("customer_partner_id")
                with self.db.con:
                    self.db.con.execute(
                        "DELETE FROM partner_routes WHERE route_id=? AND role='customer'",
                        (route_id,))
                if partner_id is not None:
                    self.partner_page.registry.link_route(int(partner_id), route_id, "customer")
            return route_id

        self.db.save_route = save_and_link_route
        self.navigation.addItem("Контрагенты")
        self.navigation.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.navigation.item(6).setSizeHint(QSize(0, 52))
        self.navigation.item(6).setToolTip("Компании, водители, машины и распознавание документов")
        self.route_note.setReadOnly(False)
        self.route_note.setPlaceholderText("Редактируй заметку и нажми «Сохранить заметку»")
        self.note_save = QPushButton("Сохранить заметку")
        self.note_save.clicked.connect(self.save_selected_note)
        self.route_note.parentWidget().layout().addWidget(self.note_save)
        self.route_card_button = QPushButton("Карточка")
        self.route_card_button.clicked.connect(lambda: self.navigation.setCurrentRow(3))
        card_layout = self._layout_containing(self.route_edit_button.parentWidget().layout(), self.route_edit_button)
        if card_layout is not None:
            card_layout.insertWidget(0, self.route_card_button, 1)
        self.finish_button = QPushButton("Завершить рейс")
        self.finish_button.setObjectName("primary")
        self.finish_button.clicked.connect(self.finish_selected_route)
        self._update_finish_button()
        action_layout = self._layout_containing(self.route_close_button.parentWidget().layout(), self.route_close_button)
        if action_layout is not None:
            action_layout.insertWidget(1, self.finish_button, 1)
        else:
            self.route_close_button.parentWidget().layout().addWidget(self.finish_button)
        icon_path = stable_app.app_asset("nav_search.png")
        if icon_path.is_file():
            from PySide6.QtGui import QIcon
            self.navigation.item(6).setIcon(QIcon(str(icon_path)))

    @staticmethod
    def _layout_containing(layout, target):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is target:
                return layout
            child = item.layout()
            if child:
                found = LogistWindow12._layout_containing(child, target)
                if found is not None:
                    return found
        return None

    def refresh_route_details(self, *_):
        super().refresh_route_details()
        self._update_finish_button()

    def _update_finish_button(self):
        if not hasattr(self, "finish_button"):
            return
        selected = self.selected_route_id()
        route = self.db.get_route(selected) if selected else None
        tracking = self.db.tracking(selected) if selected else None
        can_finish = bool(
            route and route["status"] == "Закрыт" and not route["archived"]
            and not route["deleted_at"]
            and tracking and tracking["phase"] in ("В пути", "Выгружен", "Завершён"))
        self.finish_button.setEnabled(can_finish)
        if hasattr(self, "note_save"):
            self.note_save.setEnabled(bool(route and not route["deleted_at"]))

    def save_selected_note(self):
        route_id = self.selected_route_id()
        if not route_id:
            stable_app.QMessageBox.information(self, "Выбери рейс", "Сначала выбери рейс.")
            return
        record = self.db.get_route(route_id)
        if record is None:
            return
        record["note"] = self.route_note.toPlainText()
        try:
            self.db.save_route(record)
            self.refresh_routes()
            self.statusBar().showMessage("Заметка сохранена", 4000)
        except Exception as exc:
            stable_app.QMessageBox.warning(self, "Не сохранено", str(exc))

    def finish_selected_route(self):
        route_id = self.selected_route_id()
        if not route_id:
            stable_app.QMessageBox.information(self, "Выбери рейс", "Сначала выбери рейс.")
            return
        answer = stable_app.QMessageBox.question(
            self, "Завершить перевозку",
            "Подтверждаешь фактическую выгрузку? Рейс уйдёт в архив; "
            "ожидание документов не будет блокировать завершение.",
            stable_app.QMessageBox.StandardButton.Yes | stable_app.QMessageBox.StandardButton.No,
            stable_app.QMessageBox.StandardButton.No)
        if answer != stable_app.QMessageBox.StandardButton.Yes:
            return
        try:
            finish_after_unloading(self.db, route_id)
            self.refresh_all()
            self.navigation.setCurrentRow(4)
        except Exception as exc:
            stable_app.QMessageBox.warning(self, "Не удалось завершить рейс", str(exc))

    def _on_update_checked(self, manifest: object, manual: bool):
        self._update_checking = False
        self.statusBar().clearMessage()
        if not manifest:
            if manual:
                stable_app.QMessageBox.information(
                    self, "Обновления", f"Установлена актуальная версия {stable_app.APP_VERSION}.")
            return
        version = dict(manifest)["version"]
        popup = stable_app.QMessageBox(self)
        popup.setWindowTitle("Обновление LogistDesk")
        popup.setText(f"Доступна версия {version}")
        update = popup.addButton(
            "Обновить", stable_app.QMessageBox.ButtonRole.AcceptRole)
        popup.addButton(
            "Позже", stable_app.QMessageBox.ButtonRole.RejectRole)
        popup.exec()
        if popup.clickedButton() is update:
            self._download_update(dict(manifest))

    def eventFilter(self, watched, event):
        if (getattr(self, "_draft_host", None) is watched
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Show,
                                     QEvent.Type.LayoutRequest)):
            # The main window and its central layout do not always resize in
            # the same event. A queued reposition catches maximized startup.
            QTimer.singleShot(0, self._place_draft_bar)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        # Refresh after Qt has calculated the maximized central-widget size.
        QTimer.singleShot(0, self._refresh_draft_bar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_draft_bar"):
            QTimer.singleShot(0, self._place_draft_bar)

    def _place_draft_bar(self):
        if not hasattr(self, "_draft_bar") or not self._draft_bar.isVisible():
            return
        host = self._draft_host
        if host.width() < 50 or host.height() < 80:
            return
        width = min(335, host.width() - 24)
        desired_height = 47 + 44 * min(self._draft_rows_count, 5) + 16
        height = min(desired_height, max(60, host.height() - 24))
        self._draft_bar.resize(width, height)
        self._draft_bar.move(max(0, host.width() - width - 12),
                             max(0, host.height() - height - 12))
        self._draft_bar.raise_()

    def _refresh_draft_bar(self):
        if not hasattr(self, "_draft_bar"):
            return
        layout = self._draft_list_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        stored = self.db.con.execute(
            "SELECT form_key, updated_at FROM form_drafts "
            "WHERE form_key LIKE 'new-route:%' OR form_key='new-route' "
            "ORDER BY updated_at DESC"
        ).fetchall() if "form_drafts" in {
            row[0] for row in self.db.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")} else []
        # Show both persisted drafts and brand-new, still-open composition windows.
        items = list(self._draft_windows.keys())
        items.extend(row[0] for row in stored if row[0] not in self._draft_windows)
        self._draft_rows_count = len(items)
        self._draft_title.setText(f"Черновики рейсов · {len(items)}")
        store = DraftStore(self.db) if items else None
        for key in items:
            saved = store.load(key) if store else {}
            fields = saved.get("fields") or {}
            origin = str(fields.get("origin") or "").strip()
            destination = str(fields.get("destination") or "").strip()
            label_text = (f"{origin or '?'} → {destination or '?'}"
                          if origin or destination else "Новый рейс")
            row = QWidget(self._draft_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            open_button = QPushButton(label_text, row)
            open_button.setToolTip("Открыть и продолжить этот черновик")
            open_button.clicked.connect(
                lambda checked=False, k=key: self.resume_route_draft(k))
            row_layout.addWidget(open_button, 1)
            delete_button = QPushButton("×", row)
            delete_button.setToolTip("Удалить этот черновик")
            delete_button.setAccessibleName("Удалить черновик " + label_text)
            delete_button.setFixedWidth(30)
            delete_button.clicked.connect(
                lambda checked=False, k=key: self.delete_route_draft(k))
            row_layout.addWidget(delete_button)
            layout.addWidget(row)
        self._draft_bar.setVisible(bool(items))
        if items:
            self._place_draft_bar()

    def delete_route_draft(self, key):
        if stable_app.QMessageBox.question(
            self, "Удалить черновик?",
            "Черновик рейса будет удалён без возможности восстановления. "
            "Сам сохранённый рейс (если он уже есть) не затрагивается.",
            stable_app.QMessageBox.StandardButton.Yes
            | stable_app.QMessageBox.StandardButton.No,
            stable_app.QMessageBox.StandardButton.No
        ) != stable_app.QMessageBox.StandardButton.Yes:
            return
        dialog = self._draft_windows.get(key)
        if dialog is not None:
            controller = getattr(dialog, "_drafts", None)
            if controller is not None:
                # Reject normally autosaves dirty fields; cancel that save
                # before clearing the draft to prevent a zombie reappearing.
                controller.timer.stop()
                controller._dirty = False
            dialog.reject()
        DraftStore(self.db).clear(key)
        self._refresh_draft_bar()

    def add_route(self):
        """Open an independent, non-modal route draft each time."""
        self._open_route_draft()

    def resume_route_draft(self, key):
        if key in self._draft_windows:
            dialog = self._draft_windows[key]
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
        else:
            self._open_route_draft(key)

    def _open_route_draft(self, key=None):
        key = key or "new-route:" + uuid.uuid4().hex
        dialog = RouteDialog12(self.db, parent=self, draft_key=key)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle("Новый рейс · LogistDesk")
        minimize = QPushButton("Свернуть в черновики")
        minimize.clicked.connect(
            lambda: self._minimize_route_draft(key, dialog))
        dialog.layout().insertWidget(1, minimize)
        self._draft_windows[key] = dialog
        if getattr(dialog, "_drafts", None) is not None:
            # New content appears in the taskbar after autosave even if
            # the dialog has never been minimized.
            dialog._drafts.timer.timeout.connect(self._refresh_draft_bar)
        self._refresh_draft_bar()
        dialog.finished.connect(
            lambda result, k=key, d=dialog: self._route_draft_finished(k, d, result))
        dialog.show()
        dialog.raise_()

    def _minimize_route_draft(self, key, dialog):
        if getattr(dialog, "_drafts", None):
            dialog._drafts._dirty = True
            dialog._drafts.save()
        dialog.hide()
        self._refresh_draft_bar()

    def _route_draft_finished(self, key, dialog, result):
        self._draft_windows.pop(key, None)
        if result == dialog.DialogCode.Accepted:
            try:
                self.db.save_route(dialog.payload())
                self.refresh_all()
            except Exception as exc:
                stable_app.QMessageBox.critical(self, "Ошибка сохранения рейса", str(exc))
                if getattr(dialog, "_drafts", None):
                    dialog._drafts.store.save(key, dialog._drafts.values())
        self._refresh_draft_bar()

    def refresh_today(self, *_):
        super().refresh_today()
        if hasattr(self, "_active_trips"):
            self._active_trips.refresh()

    def navigate(self, index: int):
        if index != 6:
            return super().navigate(index)
        self.centralWidget().setStyleSheet("")
        self.archive_only = False
        self.deleted_only = False
        self.new_route_button.hide()
        self.new_call_button.setText("+ Новый звонок")
        self.pages.setCurrentWidget(self.partner_page)
        self.page_title.setText("Контрагенты")
        self.page_caption.setText("Компании, водители, автомобили и импорт документов")


class RouteDialog12(stable_app.RouteDialog):
    """Предлагает уже встречавшиеся города без обращения к интернету."""

    def __init__(self, db, record=None, parent=None, draft_key=None):
        super().__init__(db, record=record, parent=parent)
        setup_city_completers(self, db)
        from PySide6.QtWidgets import QComboBox, QFormLayout, QScrollArea
        self.customer_combo = QComboBox(self)
        self.customer_combo.setEditable(True)
        self.customer_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.customer_combo.addItem("Не выбран", None)
        from partner_registry import PartnerRegistry
        self.customer_registry = PartnerRegistry(db)
        customers = self.customer_registry.search(role="customer")
        for company in customers:
            self.customer_combo.addItem(company["name"], company["id"])
        self.customer_combo.setCurrentIndex(0)
        names = [company["name"] for company in customers]
        if names:
            customer_suggestions = QCompleter(names, self.customer_combo)
            customer_suggestions.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            customer_suggestions.setFilterMode(Qt.MatchFlag.MatchContains)
            self.customer_combo.setCompleter(customer_suggestions)
            make_popup_readable(customer_suggestions, self.customer_combo)
        if record and record.get("id"):
            selected = db.con.execute(
                "SELECT partner_id FROM partner_routes WHERE route_id=? AND role='customer'",
                (record["id"],)).fetchone()
            if selected is not None:
                index = self.customer_combo.findData(int(selected[0]))
                if index >= 0:
                    self.customer_combo.setCurrentIndex(index)
        scroll = self.layout().itemAt(0).widget()
        form = scroll.widget().layout() if isinstance(scroll, QScrollArea) else None
        if isinstance(form, QFormLayout):
            form.addRow("Заказчик (из базы)", self.customer_combo)
        if not record:
            self._drafts = DraftController(
                self, db, draft_key or ("new-route:" + uuid.uuid4().hex),
                {"has_without_vat": self.enabled, "customer": self.customer_combo})


    def payload(self):
        result = super().payload()
        text = self.customer_combo.currentText().strip()
        index = self.customer_combo.findText(text, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            result["customer_partner_id"] = self.customer_combo.itemData(index)
        elif text:
            raise ValueError("Выбери заказчика из списка или «Не выбран».")
        else:
            result["customer_partner_id"] = None
        return result


class CarrierDialog12(stable_app.CarrierDialog):
    """Автоподстановка контакта по выбранной организации из справочника."""

    def __init__(self, db, record=None, preferred_route=None, parent=None):
        super().__init__(db, record=record, preferred_route=preferred_route, parent=parent)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setMinimumWidth(780)
        self.setMinimumHeight(560)
        splitter = self.findChild(QSplitter)
        if splitter is not None and splitter.count() >= 2:
            preview = splitter.widget(1)
            preview.setMinimumWidth(280)
            splitter.insertWidget(0, preview)
            splitter.setStretchFactor(0, 4)
            splitter.setStretchFactor(1, 7)
            splitter.setSizes([400, 720])
        scroll = self.findChild(QScrollArea)
        if scroll is not None:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            if scroll.widget() is not None:
                scroll.widget().layout().setContentsMargins(12, 12, 12, 16)
        # The 265-pixel fixed question labels prevented the form from fitting at 125% DPI.
        for label in self.findChildren(stable_app.QLabel):
            if label.minimumWidth() == 265 and label.maximumWidth() == 265:
                label.setFixedWidth(170)
                label.setWordWrap(True)
        preview = self.findChild(QFrame, "routePreview")
        if preview is not None:
            preview.setStyleSheet("QFrame#routePreview {border:2px solid #527995; "
                                  "border-radius:10px; background:#192b3b;}")

        for form in self.findChildren(QFormLayout):
            for key in ("customer_status", "customer_agreed_rate"):
                field = self.fields.get(key)
                if field is not None:
                    label = form.labelForField(field)
                    if label is not None:
                        label.hide()
                        field.hide()
        for label in self.findChildren(stable_app.QLabel):
            if label.text() == "Ставка и согласование":
                label.setText("Ставка перевозчика")
        for key, widget in self.fields.items():
            if isinstance(widget, QLineEdit):
                if "phone" in key:
                    bind_phone(widget)
                elif "date" in key:
                    bind_date(widget)
        self._add_visibility_menu()
        from partner_registry import PartnerRegistry
        rows = PartnerRegistry(db).search(role="carrier")
        self._partner_suggestions = {}
        for partner in rows:
            key = partner["name"].casefold()
            self._partner_suggestions.setdefault(key, []).append(partner)
        names = sorted({p["name"] for p in rows})
        if names:
            completer = QCompleter(names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.fields["carrier"].setCompleter(completer)
            make_popup_readable(completer, self.fields["carrier"])
            completer.activated[str].connect(self._prefill)
            self.fields["carrier"].editingFinished.connect(
                lambda: self._prefill(self.fields["carrier"].text()))
        self._registry = PartnerRegistry(db)
        self.saved_driver = QComboBox(self)
        self.saved_vehicle = QComboBox(self)
        self.saved_driver.addItem("Не выбран", None)
        self.saved_vehicle.addItem("Не выбрана", None)
        form = LogistWindow12._layout_containing(
            self.fields["carrier"].parentWidget().layout(), self.fields["carrier"])
        if isinstance(form, QFormLayout):
            form.addRow("Водитель из базы", self.saved_driver)
            form.addRow("Автомобиль из базы", self.saved_vehicle)
        self.saved_driver.currentIndexChanged.connect(self._choose_driver)
        self.fields["carrier"].editingFinished.connect(
            lambda: self._prefill(self.fields["carrier"].text()))
        self._prefill(self.fields["carrier"].text())
        if record:
            asset = db.con.execute(
                "SELECT driver_id, vehicle_id FROM call_resources WHERE carrier_call_id=?",
                (record.get("id"),)).fetchone()
            if asset:
                driver_idx = self.saved_driver.findData(asset[0])
                if driver_idx >= 0:
                    self.saved_driver.setCurrentIndex(driver_idx)
                vehicle_idx = self.saved_vehicle.findData(asset[1])
                if vehicle_idx >= 0:
                    self.saved_vehicle.setCurrentIndex(vehicle_idx)
        self._add_draft_support(db, record)

    def _add_visibility_menu(self):
        # Compact controls replace permanently visible panels during a call.
        header = self.layout().itemAt(0).widget()
        layout = header.layout() if header is not None else None
        if layout is None:
            return
        button = QToolButton(self)
        button.setText("Скрыть / показать блоки")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for caption, name in (("Карточка рейса", "routePreview"),
                              ("Параметры звонка", "callCard"),
                              ("Ставка перевозчика", "financeCard")):
            panel = self.findChild(QFrame, name)
            if panel is None:
                continue
            action = menu.addAction(caption)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(panel.setVisible)
        button.setMenu(menu)
        layout.addWidget(button)

    def _add_draft_support(self, db, record):
        if not record:
            extra = {}
            if hasattr(self, "payment_spoken"):
                extra["payment_spoken"] = self.payment_spoken
            extra["driver"] = self.saved_driver
            extra["vehicle"] = self.saved_vehicle
            self._drafts = DraftController(self, db, "new-call", extra)

    def _prefill(self, name):
        partners = self._partner_suggestions.get(str(name).strip().casefold(), [])
        self._selected_company = partners[0] if len(partners) == 1 else None
        if self._selected_company and not self.fields["phone"].text().strip():
            self.fields["phone"].setText(self._selected_company.get("phone") or "")
        self.saved_driver.blockSignals(True)
        self.saved_driver.clear()
        self.saved_driver.addItem("Не выбран", None)
        self.saved_vehicle.clear()
        self.saved_vehicle.addItem("Не выбрана", None)
        if self._selected_company:
            for driver in self._registry.drivers(self._selected_company["id"]):
                title = " ".join(x for x in (driver["surname"], driver["first_name"],
                                             driver["patronymic"]) if x)
                self.saved_driver.addItem(title, driver["id"])
            for vehicle in self._registry.vehicles(self._selected_company["id"]):
                self.saved_vehicle.addItem(
                    " · ".join(x for x in (vehicle["plate"], vehicle["brand"],
                                            vehicle["model"]) if x), vehicle["id"])
        self.saved_driver.blockSignals(False)

    def _choose_driver(self, *_):
        driver_id = self.saved_driver.currentData()
        if driver_id is None or not getattr(self, "_selected_company", None):
            return
        person = next((x for x in self._registry.drivers(self._selected_company["id"])
                       if x["id"] == driver_id), None)
        if person and not self.fields["driver_phone"].text().strip():
            self.fields["driver_phone"].setText(person.get("phone") or "")
        linked = self._registry.vehicles_for_driver(driver_id)
        if len(linked) == 1:
            index = self.saved_vehicle.findData(linked[0]["id"])
            if index >= 0:
                self.saved_vehicle.setCurrentIndex(index)

    def payload(self):
        result = super().payload()
        driver_id = self.saved_driver.currentData()
        vehicle_id = self.saved_vehicle.currentData()
        if driver_id is not None and getattr(self, "_selected_company", None):
            person = next((x for x in self._registry.drivers(self._selected_company["id"])
                           if x["id"] == driver_id), None)
            if person:
                result["driver_name"] = " ".join(
                    x for x in (person["surname"], person["first_name"],
                                person["patronymic"]) if x)
                if not result.get("driver_phone"):
                    result["driver_phone"] = person.get("phone") or ""
        result["selected_driver_id"] = driver_id
        result["selected_vehicle_id"] = vehicle_id
        return result


stable_app.LogistWindow = LogistWindow12
stable_app.RouteDialog = RouteDialog12
stable_app.CarrierDialog = CarrierDialog12


if __name__ == "__main__":
    # Превью никогда не должно изменять реальную базу 1.1.3 на этом ПК.
    os.environ["LOGIST_DATA_DIR"] = str(
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "LogistDesk12Preview")
    sys.exit(stable_app.main())
