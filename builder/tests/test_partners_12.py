"""Регрессионные тесты нового справочника LogistDesk 1.2."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from database import Database
from partner_registry import PartnerRegistry
from document_extract import parse_text, kind_from_text
from call_bridge import register_call, import_legacy_calls
from route_completion import finish_after_unloading


class PartnerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "logist.db"
        self.db = Database(self.path)
        self.registry = PartnerRegistry(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_partner_persists_and_is_searchable(self):
        pid = self.registry.save_partner({
            "name": 'ООО "Тест Транс"', "role": "carrier", "inn": "1650123456",
            "phone": "+7 999 111-22-33", "bank": "Тестовый банк",
        })
        self.assertEqual(self.registry.get_partner(pid)["inn"], "1650123456")
        self.assertEqual(len(self.registry.search("Тест Транс", "carrier")), 1)
        self.assertEqual(len(self.registry.search("1650123456", "customer")), 0)
        self.db.close()
        self.db = Database(self.path)
        self.registry = PartnerRegistry(self.db)
        self.assertEqual(self.registry.get_partner(pid)["name"], 'ООО "Тест Транс"')

    def test_duplicate_inn_blocked(self):
        self.registry.save_partner({"name": "Первый", "role": "both", "inn": "1234567890"})
        with self.assertRaisesRegex(ValueError, "уже существует"):
            self.registry.save_partner({"name": "Второй", "role": "carrier", "inn": "1234567890"})

    def test_driver_vehicle_and_links(self):
        pid = self.registry.save_partner({"name": "Компания", "role": "both"})
        driver = self.registry.save_driver({
            "partner_id": pid, "surname": "Иванов", "first_name": "Иван",
            "license_number": "9911223344",
        })
        vehicle = self.registry.save_vehicle({
            "partner_id": pid, "plate": "А123ВС16",
            "vin": "XTA210990Y1234567",
        })
        self.assertEqual(self.registry.drivers(pid)[0]["id"], driver)
        self.assertEqual(self.registry.vehicles(pid)[0]["id"], vehicle)
        self.registry.link_driver_vehicle(driver, vehicle)
        self.registry.link_driver_vehicle(driver, vehicle)
        self.assertEqual([v["id"] for v in self.registry.vehicles_for_driver(driver)], [vehicle])
        with self.assertRaisesRegex(ValueError, "VIN"):
            self.registry.save_vehicle({
                "partner_id": pid, "plate": "А555ВС16", "vin": "XTA210990Y1234567",
            })
        self.db.save_route({"id": "R001", "origin": "Казань", "destination": "Москва"})
        self.registry.link_route(pid, "R001", "carrier")
        self.assertEqual(self.registry.history(pid)[0]["route_id"] if "route_id" in self.registry.history(pid)[0]
                         else self.registry.history(pid)[0]["id"], "R001")

    def test_migration_backups_original(self):
        self.assertTrue(list((self.path.parent / "backups").glob("*.db")))
        pid = self.registry.save_partner({"name": "Резерв", "role": "customer"})
        self.assertEqual(self.registry.get_partner(pid)["role"], "customer")

    def test_finish_unloaded_trip_without_document_gate(self):
        self.db.save_route({"id": "R021", "origin": "Казань", "destination": "Москва"})
        call = self.db.save_carrier({
            "route_id": "R021", "carrier": "Компания", "desired_rate": 50000,
        })
        self.db.close_route("R021", call, "2026-10-27T09:00")
        with self.assertRaisesRegex(ValueError, "загрузку"):
            finish_after_unloading(self.db, "R021")
        self.db.confirm_loaded("R021", "2026-10-28T09:00")
        finish_after_unloading(self.db, "R021")
        self.assertEqual(self.db.get_route("R021")["archived"], 1)
        self.assertEqual(self.db.tracking("R021")["phase"], "Завершён")
        self.assertEqual(self.db.get_route("R021")["status"], "Закрыт")
        self.assertEqual(self.db.con.execute(
            "SELECT COUNT(*) FROM reminders WHERE route_id='R021' AND kind='signed_docs' AND state='pending'"
        ).fetchone()[0], 1)

    def test_delete_company_preserves_route_and_call(self):
        self.db.save_route({"id": "R022", "origin": "Уфа", "destination": "Москва"})
        call_id = self.db.save_carrier({
            "route_id": "R022", "carrier": "ООО Удалить", "phone": "+79000000000",
        })
        partner_id = register_call(self.registry, {
            "route_id": "R022", "carrier": "ООО Удалить", "phone": "+79000000000",
        }, call_id)
        driver_id = self.registry.save_driver({
            "partner_id": partner_id, "surname": "Иванов", "first_name": "Иван",
        })
        vehicle_id = self.registry.save_vehicle({
            "partner_id": partner_id, "plate": "А123ВС16",
        })
        self.registry.link_driver_vehicle(driver_id, vehicle_id)
        self.registry.delete_partner(partner_id)
        self.assertIsNone(self.registry.get_partner(partner_id))
        self.assertIsNotNone(self.db.get_route("R022"))
        self.assertIsNotNone(self.db.get_carrier(call_id))
        self.assertEqual(self.db.con.execute(
            "SELECT COUNT(*) FROM partner_drivers WHERE partner_id=?", (partner_id,)
        ).fetchone()[0], 0)

    def test_import_existing_calls_is_idempotent(self):
        self.db.save_route({"id": "R015", "origin": "Казань", "destination": "Москва"})
        call = {"route_id": "R015", "carrier": "ООО Пример", "phone": "+79000000000",
                "driver_name": "Иванов Иван", "driver_phone": "+79001111111"}
        call_id = self.db.save_carrier(call)
        person_id = register_call(self.registry, call, call_id)
        self.assertEqual(person_id, register_call(self.registry, call, call_id))
        self.assertEqual(len(self.registry.search("ООО Пример")), 1)
        self.assertEqual(len(self.registry.drivers(person_id)), 1)
        self.assertEqual(len(self.registry.history(person_id)), 1)
        self.assertEqual(import_legacy_calls(self.registry)["total"], 1)
        self.assertEqual(len(self.registry.search("ООО Пример")), 1)

    def test_preserve_legacy_routes(self):
        self.db.save_route({"id": "R007", "sender": "Бикотекс", "origin": "Челны",
                            "destination": "Москва"})
        self.registry.save_partner({"name": "Организация", "role": "carrier"})
        self.assertEqual(self.db.get_route("R007")["sender"], "Бикотекс")


class DocumentExtractTests(unittest.TestCase):
    def test_partner_card(self):
        text = 'ООО «Вектор»\nИНН: 1234567890\nКПП: 165001001\nБИК: 049205777\nEmail: test@v.ru'
        kind, data = parse_text(text)
        self.assertEqual(kind, "partner")
        self.assertEqual(data["inn"], "1234567890")
        self.assertEqual(data["kpp"], "165001001")
        self.assertEqual(data["bik"], "049205777")
        self.assertEqual(data["email"], "test@v.ru")

    def test_document_kind(self):
        self.assertEqual(kind_from_text("СВИДЕТЕЛЬСТВО О РЕГИСТРАЦИИ ТС VIN"), "vehicle")
        self.assertEqual(kind_from_text("ВОДИТЕЛЬСКОЕ УДОСТОВЕРЕНИЕ"), "driver")
        self.assertEqual(kind_from_text("ПАСПОРТ ГРАЖДАНИНА"), "driver")


class PartnerUiSmokeTests(unittest.TestCase):
    def test_registry_page_and_ctrl_v_clipboard(self):
        from unittest.mock import patch
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        from partners_ui import RegistryPage
        qt = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "preview.db")
            page = RegistryPage(db)
            self.assertEqual(page.tabs.count(), 3)
            self.assertIn("inn", page.partner_fields)
            page.partner_fields["name"].setText("ООО Пример")
            with patch("partners_ui.QMessageBox.information", return_value=0):
                page.save_partner()
            self.assertEqual(len(page.registry.search("ООО Пример")), 1)
            image = QImage(60, 40, QImage.Format.Format_RGB32)
            image.fill(0xFFFFFF)
            QApplication.clipboard().setImage(image)
            with patch("partners_ui.image_text", return_value="ИНН: 1234567890") as ocr, \
                    patch.object(page, "_review") as review:
                page.paste_clipboard()
                ocr.assert_called_once()
                review.assert_called_once()
                args, kwargs = review.call_args
                self.assertEqual(args, ("ИНН: 1234567890",))
                self.assertEqual(kwargs["filename"], "Скриншот.png")
                self.assertTrue(kwargs["original"].startswith(bytes([137, 80, 78, 71])))
            page.close()
            page.deleteLater()
            qt.processEvents()
            db.close()


if __name__ == "__main__":
    unittest.main()
