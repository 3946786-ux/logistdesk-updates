"""Защищённый перенос справочника между двумя отдельными установками."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from database import Database
from partner_registry import PartnerRegistry
from portable_transfer import export_contacts, import_contacts


class PortableTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.a = Database(base / "a.db")
        self.b = Database(base / "b.db")
        self.source = PartnerRegistry(self.a)
        self.target = PartnerRegistry(self.b)
        self.path = base / "move.ldx"

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.temp.cleanup()

    def populate(self):
        pid = self.source.save_partner({
            "name": "ООО ТЕСТ", "role": "carrier", "inn": "1650123456",
            "phone": "+79009992233",
        })
        self.source.save_driver({
            "partner_id": pid, "surname": "Иванов", "first_name": "Иван",
            "phone": "+79001231212", "license_number": "9112345678",
            "passport_series": "1234", "passport_number": "123456",
        })
        self.source.save_vehicle({
            "partner_id": pid, "plate": "А123ВС16", "vin": "XTA210990Y1234567",
            "registration_number": "654321",
        })
        return pid

    def test_encrypted_default_excludes_sensitive_document_fields(self):
        self.populate()
        report = export_contacts(self.source, self.path, "passphrase-12-SAFE")
        self.assertEqual(report["companies"], 1)
        raw = self.path.read_bytes()
        for secret in (b"1650123456", b"123456", b"9112345678", "Иванов".encode()):
            self.assertNotIn(secret, raw)
        result = import_contacts(self.target, self.path, "passphrase-12-SAFE")
        self.assertEqual(result["new_companies"], 1)
        self.assertEqual(result["drivers"], 1)
        company = self.target.search("ТЕСТ")[0]
        driver = self.target.drivers(company["id"])[0]
        self.assertEqual(driver["passport_series"], "")
        self.assertEqual(driver["license_number"], "")
        self.assertEqual(import_contacts(self.target, self.path, "passphrase-12-SAFE")["new_companies"], 0)
        self.assertEqual(len(self.target.drivers(company["id"])), 1)
        self.assertEqual(len(self.target.vehicles(company["id"])), 1)

    def test_explicitly_include_doc_fields(self):
        self.populate()
        export_contacts(self.source, self.path, "passphrase-12-SAFE", include_private=True)
        import_contacts(self.target, self.path, "passphrase-12-SAFE")
        company = self.target.search("ТЕСТ")[0]
        self.assertEqual(self.target.drivers(company["id"])[0]["passport_number"], "123456")

    def test_wrong_passphrase_does_not_change_existing_data(self):
        self.populate()
        export_contacts(self.source, self.path, "passphrase-12-SAFE")
        with self.assertRaisesRegex(ValueError, "пароль"):
            import_contacts(self.target, self.path, "incorrect-12-pass")
        self.assertEqual(self.target.search(), [])

    def test_collision_does_not_overwrite_original(self):
        self.populate()
        self.target.save_partner({
            "name": "ООО ТЕСТ", "role": "customer", "inn": "1650123456",
            "phone": "+79006665544",
        })
        export_contacts(self.source, self.path, "passphrase-12-SAFE")
        result = import_contacts(self.target, self.path, "passphrase-12-SAFE")
        self.assertEqual(result["new_companies"], 0)
        record = self.target.search()[0]
        self.assertEqual(record["phone"], "+79006665544")
        self.assertEqual(record["role"], "both")
        self.assertGreaterEqual(result["conflicts"], 1)


if __name__ == "__main__":
    unittest.main()
