"""End-to-end 2.1 contact exchange tests using synthetic records only."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from partner_registry import PartnerRegistry
from portable_transfer import _decrypt
from exchange21 import DeviceExchange21, _open_catalog


PASSWORD = "correct test-only passphrase for the two machines"


class TestDeviceExchange21(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.folder = root / "shared"
        self.folder.mkdir()
        self.work = Database(path=root / "work.db")
        self.home = Database(path=root / "home.db")
        self.wreg = PartnerRegistry(self.work)
        self.hreg = PartnerRegistry(self.home)
        self.wexchange = DeviceExchange21(self.wreg, self.folder, PASSWORD, "work")
        self.hexchange = DeviceExchange21(self.hreg, self.folder, PASSWORD, "home")

    def tearDown(self):
        self.wexchange.close()
        self.hexchange.close()
        self.work.close()
        self.home.close()
        self.temp.cleanup()

    def test_selected_partner_only_and_private_fields_excluded(self):
        chosen = self.wreg.save_partner({"name": "Тест Транс", "role": "carrier",
                                         "inn": "7700123456", "phone": "+7 900 000-00-01"})
        self.wreg.save_partner({"name": "Не передавать", "role": "carrier",
                                "inn": "7700123457"})
        self.wreg.save_driver({"partner_id": chosen, "surname": "Тестов",
                               "phone": "+7 900 000-00-02",
                               "passport_number": "PRIVATE-NO-SEND",
                               "license_number": "1234567890"})
        self.wreg.save_vehicle({"partner_id": chosen, "plate": "А001АА77",
                                "brand": "Тест", "body_type": "Тент",
                                "registration_number": "SECRET-STS"})
        packet = self.wexchange.transfer_partner(chosen)
        decrypted = _decrypt(packet, PASSWORD)
        self.assertEqual(len(decrypted["entries"]), 1)
        partner = decrypted["entries"][0]
        self.assertEqual(partner["partner"]["name"], "Тест Транс")
        self.assertNotIn("passport_number", partner["drivers"][0])
        self.assertNotIn("license_number", partner["drivers"][0])
        self.assertNotIn("registration_number", partner["vehicles"][0])
        self.assertFalse(decrypted["private_included"])

        files = self.hexchange.pending_transfers()
        self.assertEqual(files, [packet])
        report = self.hexchange.import_transfer(files[0])
        self.assertEqual(report["new_companies"], 1)
        self.assertEqual(self.hexchange.pending_transfers(), [])
        self.assertTrue(self.hexchange.import_transfer(files[0])["already_imported"])
        self.assertEqual(len(self.hreg.search()), 1)
        self.assertEqual(self.hreg.search()[0]["name"], "Тест Транс")

    def test_workplace_search_decrypts_only_minimal_index(self):
        chosen = self.hreg.save_partner({"name": "Рейс Тент", "role": "carrier",
                                         "inn": "7700987654", "phone": "+7 900 000-01-00",
                                         "bank": "BANK-PRIVATE"})
        self.hreg.save_vehicle({"partner_id": chosen, "brand": "Тест", "plate": "Х123ХХ77",
                                "body_type": "Тент", "registration_number": "STS PRIVATE"})
        published = self.hexchange.publish_catalog()
        self.assertEqual(published, 1)
        raw = (self.folder / "LogistDesk-Exchange-21" / "catalog.ldx21").read_bytes()
        self.assertNotIn(b"BANK-PRIVATE", raw)
        self.assertNotIn(b"STS PRIVATE", raw)
        self.assertNotIn(b"\xd0\xa2\xd0\xb5\xd0\xbd\xd1\x82", raw)
        data = _open_catalog(raw, PASSWORD)
        self.assertEqual(set(data["entries"][0]),
                         {"name", "role", "inn", "phone", "body_types", "directions"})
        self.assertEqual(self.wexchange.refresh_catalog(), 1)
        hits = self.wexchange.search_catalog("Тент")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["name"], "Рейс Тент")
        self.assertEqual(self.wreg.search(), [])  # no local full-card cache
        with self.assertRaises(ValueError):
            _open_catalog(raw, "a different passphrase longer than 12")

    def test_work_cannot_publish_home_catalog_or_import_full_cards(self):
        with self.assertRaises(ValueError):
            self.wexchange.publish_catalog()
        p = self.wreg.save_partner({"name": "Тест", "role": "carrier"})
        path = self.wexchange.transfer_partner(p)
        with self.assertRaises(ValueError):
            self.wexchange.import_transfer(path)


if __name__ == "__main__":
    unittest.main()
