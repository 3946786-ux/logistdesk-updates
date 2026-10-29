"""Release-gate checks for user-reported LogistDesk usability problems."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QTableWidgetItem
from database import Database
from input_formatting import ru_phone, short_date, series_number
from partner_registry import PartnerRegistry
from today_active import ActiveTripsPanel
from ui_tracking import CloseRouteDialog


class InputFormattingTests(unittest.TestCase):
    def test_russian_mobile_and_international_preservation(self):
        for value in ("89274523635", "79274523635", "+79274523635"):
            self.assertEqual(ru_phone(value), "+7(927) 452-36-35")
        self.assertEqual(ru_phone("8927"), "8927")
        self.assertEqual(ru_phone("+491701234567"), "+491701234567")

    def test_short_date_and_merged_docs(self):
        self.assertEqual(short_date("271026"), "27.10.26")
        self.assertEqual(short_date("2710"), "27.10")
        self.assertEqual(short_date("27.10.2026"), "27.10.2026")
        self.assertEqual(short_date("завтра"), "завтра")
        self.assertEqual(series_number("1234567890"), "1234 567890")


class ActiveTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.save_route({"id": "R201", "origin": "Казань", "destination": "Уфа"})
        self.carrier = self.db.save_carrier({"route_id": "R201", "carrier": "ООО Тест"})

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_closed_without_date_visible_and_later_schedulable(self):
        self.db.close_route("R201", self.carrier)
        panel = ActiveTripsPanel(self.db, lambda: None)
        panel.refresh()
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertIn("Уточнить", panel.table.item(0, 2).text())
        self.db.delay_loading("R201", "2026-11-10T10:00")
        panel.refresh()
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertNotIn("Уточнить", panel.table.item(0, 2).text())
        self.assertEqual(len(self.db.reminder_rows()), 2)
        panel.deleteLater()

    def test_close_dialog_requires_explicit_date_or_later(self):
        route = self.db.get_route("R201")
        calls = self.db.carriers(route_id="R201")
        dialog = CloseRouteDialog(route, calls)
        try:
            self.assertFalse(dialog.use_load_time.isChecked())
            self.assertTrue(dialog.load_time.isEnabled())
            with patch("ui_tracking.QMessageBox.information", return_value=0):
                dialog.validate()
                self.assertEqual(dialog.result(), 0)
            dialog.accept_without_date()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.values()["load_due_at"], "")
        finally:
            dialog.deleteLater()

    def test_optional_vehicle_body_fields_preserved(self):
        registry = PartnerRegistry(self.db)
        partner = registry.save_partner({"name": "ООО Перевозчик", "role": "carrier"})
        ident = registry.save_vehicle({
            "partner_id": partner, "brand": "КамАЗ", "plate": "А123ВС16",
            "body_type": "Тент", "payload_t": "20", "volume_m3": "82",
            "body_length_m": "13.6", "body_width_m": "2.45",
            "body_height_m": "2.6", "trailer_brand": "Тонар",
            "trailer_plate": "АН123416",
        })
        record = registry.vehicles(partner)[0]
        self.assertEqual(record["id"], ident)
        self.assertEqual(record["body_type"], "Тент")
        self.assertEqual(record["trailer_brand"], "Тонар")
        self.db.close()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.assertEqual(PartnerRegistry(self.db).vehicles(partner)[0]["payload_t"], "20")


if __name__ == "__main__":
    unittest.main()
