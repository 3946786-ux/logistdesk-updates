"""UI integration and encrypted-profile upgrade smoke for LogistDesk 2.1."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from database import Database
from exchange21 import DeviceExchange21
from exchange_ui21 import device_role
from operations_sync21 import OperationsSync21
from partner_registry import PartnerRegistry
from partners_ui import RegistryPage
from security import SecurityVault


PHRASE = "safe test only transfer phrase for two devices"


class ExchangeUISmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_explicit_buttons_do_not_enable_cloud_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.db")
            page = RegistryPage(db)
            try:
                c = page.exchange21_controls
                self.assertEqual(c.transfer_button.text(), "Перенести контрагента")
                self.assertFalse(c.sync_now_button.isEnabled())
                self.assertIsNone(c.exchange)
                self.assertEqual(device_role(db), "")
            finally:
                c.timer.stop()
                page.close()
                db.close()

    def test_work_mode_does_not_register_carrier_as_partner(self):
        import app
        import app12
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "test.db")
            db.save_route({"id": "R777", "origin": "Казань", "destination": "Москва"})
            original = (app.LogistWindow, app.CarrierDialog, app.RouteDialog)
            try:
                with patch.object(app12.stable_app, "Database", return_value=db):
                    window = app12.LogistWindow12()
                    try:
                        with db.con:
                            db.con.execute(
                                "CREATE TABLE IF NOT EXISTS exchange21_device("
                                "id INTEGER PRIMARY KEY CHECK(id=1), role TEXT NOT NULL)")
                            db.con.execute(
                                "INSERT INTO exchange21_device(id,role) VALUES(1,'work')")
                        self.assertEqual(device_role(db), "work")
                        db.save_carrier({
                            "route_id": "R777",
                            "carrier": "ООО Только звонок",
                            "phone": "+7 900 000-00-00",
                        })
                        self.assertEqual(window.partner_page.registry.search(), [])
                        self.assertEqual(len(db.carriers(route_id="R777")), 1)
                    finally:
                        window.reminder_timer.stop()
                        window._really_quit = True
                        window.close()
                        self.app.processEvents()
            finally:
                app.LogistWindow, app.CarrierDialog, app.RouteDialog = original


class EncryptedSyncUpgrade(unittest.TestCase):
    def test_vault_and_pin_survive_sync_schema_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "sync"
            shared.mkdir()
            data = root / "profile"
            vault = SecurityVault(data)
            vault.setup_pin("Tester", "2468", "2468")
            db = Database(vault=vault)
            db.save_route({"id": "R007", "origin": "Нижнекамск",
                           "destination": "Казань", "note": "Не потерять"})
            registry = PartnerRegistry(db)
            exchange = DeviceExchange21(registry, shared, PHRASE, "home")
            sync = OperationsSync21(db, shared, PHRASE)
            self.assertEqual(sync.sync_once()["sent"], 1)
            exchange.publish_catalog()
            exchange.close()
            sync.close()
            db.close()
            last = SecurityVault(data)
            last.unlock_pin("2468")
            opened = Database(vault=last)
            self.assertEqual(opened.get_route("R007")["note"], "Не потерять")
            self.assertEqual(opened.get_route("R007")["origin"], "Нижнекамск")
            row = opened.con.execute(
                "SELECT COUNT(*) FROM ops21_links WHERE kind='route'").fetchone()
            self.assertEqual(row[0], 1)
            opened.close()


if __name__ == "__main__":
    unittest.main()
