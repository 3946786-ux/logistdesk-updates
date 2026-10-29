"""Opt-in Qt controls for LogistDesk 2.1 device exchange.

No automatic activation and no passwords stored to disk.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox, QPushButton,
)

from exchange21 import DeviceExchange21
from operations_sync21 import OperationsSync21
from portable_transfer import export_contacts


def device_role(db) -> str:
    tables = {r[0] for r in db.con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "exchange21_device" not in tables:
        return ""
    row = db.con.execute("SELECT role FROM exchange21_device WHERE id=1").fetchone()
    return row[0] if row and row[0] in ("work", "home") else ""


class Exchange21Controls:
    def __init__(self, page, left):
        self.page = page
        self.exchange = None
        self.operations = None
        self.timer = QTimer(page)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.poll)
        self.setup_button = QPushButton("Связать компьютеры")
        self.setup_button.clicked.connect(self.configure)
        left.addWidget(self.setup_button)
        self.transfer_button = QPushButton("Перенести контрагента")
        self.transfer_button.clicked.connect(self.transfer_selected)
        left.addWidget(self.transfer_button)
        self.remote_search_button = QPushButton("Найти перевозчика в личной базе")
        self.remote_search_button.clicked.connect(self.search_remote)
        left.addWidget(self.remote_search_button)
        self.incoming_button = QPushButton("Входящие контрагенты")
        self.incoming_button.clicked.connect(self.receive)
        left.addWidget(self.incoming_button)
        self.catalog_button = QPushButton("Обновить каталог для поиска")
        self.catalog_button.clicked.connect(self.publish_catalog)
        left.addWidget(self.catalog_button)
        self.sync_now_button = QPushButton("Синхронизировать сейчас")
        self.sync_now_button.clicked.connect(self.poll)
        left.addWidget(self.sync_now_button)
        from PySide6.QtWidgets import QLabel
        self.sync_label = QLabel("Синхронизация выключена")
        self.sync_label.setWordWrap(True)
        left.addWidget(self.sync_label)
        self._refresh_buttons()

    def _refresh_buttons(self):
        role = device_role(self.page.registry.db)
        self.remote_search_button.setVisible(role == "work")
        self.incoming_button.setVisible(role == "home")
        self.catalog_button.setVisible(role == "home")
        self.sync_now_button.setEnabled(self.operations is not None)
        self.setup_button.setText(
            "Обмен: " + ("работа" if role == "work" else "дом" if role == "home" else "не настроен")
            + (" · включён" if self.exchange else " · выключен"))
        # Legacy full-address-book two-way export is unsafe in split-base mode.
        if role:
            self.page.sync_button.setEnabled(False)
            self.page.sync_button.setToolTip(
                "В режиме двух компьютеров используйте «Перенести контрагента».")

    def configure(self):
        if self.exchange:
            self.timer.stop()
            self.exchange.close()
            if self.operations:
                self.operations.close()
            self.operations = None
            self.exchange = None
            self.sync_label.setText("Синхронизация выключена")
            self._refresh_buttons()
            return
        answer = QMessageBox.question(
            self.page, "Обмен между компьютерами",
            "Нужна общая папка, которую синхронизирует разрешённый облачный сервис.\\n"
            "Рабочие данные передаются только при наличии права на их перенос.\\n"
            "В облаке пакеты зашифрованы, пароли не сохраняются. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        options = ["Работа", "Дом"]
        choice, ok = QInputDialog.getItem(
            self.page, "Тип компьютера", "Где установлен LogistDesk?",
            options, 0, False)
        if not ok:
            return
        role = "work" if choice == "Работа" else "home"
        folder = QFileDialog.getExistingDirectory(
            self.page, "Общая папка, доступная на обоих компьютерах")
        if not folder:
            return
        phrase, ok = QInputDialog.getText(
            self.page, "Пароль обмена",
            "Парольная фраза (не PIN), от 12 символов, одинаковая на обоих ПК:",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            exchanger = DeviceExchange21(self.page.registry, folder, phrase, role)
            db = self.page.registry.db
            operations = OperationsSync21(db, folder, phrase)
            tables = {r[0] for r in db.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "exchange21_device" not in tables:
                db.backup()
            with db.con:
                db.con.execute("""CREATE TABLE IF NOT EXISTS exchange21_device(
                    id INTEGER PRIMARY KEY CHECK(id=1), role TEXT NOT NULL
                )""")
                db.con.execute(
                    "INSERT INTO exchange21_device(id,role) VALUES(1,?) "
                    "ON CONFLICT(id) DO UPDATE SET role=excluded.role", (role,))
            if self.page.folder_sync:
                self.page.sync_timer.stop()
                self.page.folder_sync.close()
                self.page.folder_sync = None
            self.exchange = exchanger
            self.operations = operations
            self.timer.start()
            self.poll()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.page, "Обмен не включён", str(exc))
            return
        self._refresh_buttons()

    def transfer_selected(self):
        partner_id = self.page.partner_id
        if partner_id is None:
            QMessageBox.information(self.page, "Перенести контрагента",
                                    "Сначала выбери карточку организации.")
            return
        p = self.page.registry.get_partner(partner_id)
        if p is None:
            return
        answer = QMessageBox.question(
            self.page, "Перенести контрагента",
            f"Перенести «{p['name']}»?\\n"
            "Передаются данные выбранной компании, контакты водителей и машин. "
            "Паспорта, ВУ, СТС и файлы документов исключены.\\n"
            "Переноси только данные, которыми вправе пользоваться.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.exchange:
                path = self.exchange.transfer_partner(int(partner_id))
            else:
                path, _ = QFileDialog.getSaveFileName(
                    self.page, "Зашифрованный перенос", "Контрагент.ldx",
                    "Защищённый контакт (*.ldx)")
                if not path:
                    return
                phrase, ok = QInputDialog.getText(
                    self.page, "Пароль переноса", "Парольная фраза от 12 символов:",
                    QLineEdit.EchoMode.Password)
                if not ok:
                    return
                export_contacts(self.page.registry, path, phrase,
                                include_private=False, partner_ids={int(partner_id)})
            QMessageBox.information(
                self.page, "Контрагент подготовлен",
                "Зашифрованный пакет создан.\\n"
                "Он будет доступен на другом ПК после синхронизации общей папки.\\n"
                f"Файл: {Path(path).name}")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.page, "Не удалось перенести", str(exc))

    def receive(self):
        if not self.exchange or self.exchange.role != "home":
            QMessageBox.information(self.page, "Входящие",
                                    "Сначала включи обмен на домашнем ПК.")
            return
        try:
            pending = self.exchange.pending_transfers()
            if not pending:
                QMessageBox.information(self.page, "Входящие", "Новых карточек нет.")
                return
            chosen, ok = QInputDialog.getItem(
                self.page, "Входящие контрагенты",
                "Выбери пакет, который хочешь добавить в личную базу:",
                [p.name for p in pending], 0, False)
            if not ok:
                return
            target = next(p for p in pending if p.name == chosen)
            answer = QMessageBox.question(
                self.page, "Подтвердить импорт",
                f"Импортировать {chosen}?\\n"
                "Перед импортом создаётся резервная копия базы. "
                "Данные с несовпадающими полями не перезаписываются.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            result = self.exchange.import_transfer(target)
            self.page.reload_partners()
            self.exchange.publish_catalog()
            QMessageBox.information(
                self.page, "Контрагент перенесён",
                f"Новых компаний: {result['new_companies']}\\n"
                f"Обновлено существующих: {result['existing_companies']}\\n"
                f"Расхождений без перезаписи: {result['conflicts']}")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.page, "Ошибка приёма", str(exc))

    def publish_catalog(self):
        if not self.exchange or self.exchange.role != "home":
            QMessageBox.information(self.page, "Каталог",
                                    "Сначала включи обмен на домашнем ПК.")
            return
        try:
            total = self.exchange.publish_catalog()
            QMessageBox.information(self.page, "Каталог обновлён",
                f"Опубликовано {total} записей в зашифрованном виде. "
                "Паспорта и документы не отправлялись.")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.page, "Каталог", str(exc))

    def search_remote(self):
        if not self.exchange or self.exchange.role != "work":
            QMessageBox.information(self.page, "Поиск", "Сначала включи обмен на рабочем ПК.")
            return
        query, ok = QInputDialog.getText(
            self.page, "Личный каталог", "Название, ИНН, телефон, направление или тип кузова:")
        if not ok or not query.strip():
            return
        try:
            self.exchange.refresh_catalog()
            matches = self.exchange.search_catalog(query)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.page, "Каталог", str(exc))
            return
        if not matches:
            QMessageBox.information(self.page, "Поиск", "Совпадений нет.")
            return
        labels = [
            f"{i + 1}. {p['name']} · {p['phone']} · {p['directions'][:80]}"
            for i, p in enumerate(matches)]
        selected, ok = QInputDialog.getItem(
            self.page, "Найденные перевозчики",
            "Выбери перевозчика для добавления в рейс:", labels, 0, False)
        if not ok:
            return
        record = matches[labels.index(selected)]
        routes = self.page.registry.db.routes(include_closed=False)
        if not routes:
            QMessageBox.information(self.page, "Рейсы", "Сначала создай открытый рейс.")
            return
        route_labels = [f"{r['id']} · {r['origin']} → {r['destination']}" for r in routes]
        chosen, ok = QInputDialog.getItem(
            self.page, "Выбор рейса", "В какой рейс добавить перевозчика?",
            route_labels, 0, False)
        if not ok:
            return
        route_id = routes[route_labels.index(chosen)]["id"]
        from app import CarrierDialog
        dialog = CarrierDialog(self.page.registry.db, preferred_route=route_id, parent=self.page)
        dialog.fields["carrier"].setText(record["name"])
        dialog.fields["phone"].setText(record["phone"])
        dialog.route.select_route(route_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.page.registry.db.save_carrier(dialog.payload())
                window = self.page.window()
                if hasattr(window, "refresh_all"):
                    window.refresh_all()
                QMessageBox.information(self.page, "Готово", "Перевозчик добавлен в рейс.")
            except Exception as exc:
                QMessageBox.warning(self.page, "Не сохранено", str(exc))

    def poll(self):
        if not self.exchange:
            return
        try:
            if self.exchange.role == "work":
                self.exchange.refresh_catalog()
            else:
                self.exchange.publish_catalog()
            # HOME requires operator approval to import contacts: no auto-import.
            report = self.operations.sync_once()
            self.sync_label.setText(
                f"Обмен: получено {report['received']}, отправлено {report['sent']}; "
                f"конфликтов {report['conflicts']}, в ожидании {report['pending']}")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.timer.stop()
            if self.exchange:
                self.exchange.close()
            if self.operations:
                self.operations.close()
            self.operations = None
            self.exchange = None
            self.sync_label.setText("Обмен остановлен из-за ошибки")
            QMessageBox.warning(self.page, "Ошибка синхронизации", str(exc))
        self._refresh_buttons()
