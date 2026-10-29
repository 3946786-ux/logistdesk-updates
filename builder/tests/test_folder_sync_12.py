"""Проверка безопасной файловой синхронизации с конфликтами."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from database import Database
from partner_registry import PartnerRegistry
from folder_sync import FolderSync


class FolderSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = Path(self.temp.name)
        self.shared = home / "shared"
        self.shared.mkdir()
        self.a = Database(home / "a.db")
        self.b = Database(home / "b.db")
        self.reg_a = PartnerRegistry(self.a)
        self.reg_b = PartnerRegistry(self.b)

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.temp.cleanup()

    def test_two_way_and_repeated_no_duplicate_files(self):
        pa = self.reg_a.save_partner({"name": "Альфа", "role": "carrier", "inn": "1650123456"})
        a = FolderSync(self.reg_a, self.shared, "sync-password-12-SAFE")
        b = FolderSync(self.reg_b, self.shared, "sync-password-12-SAFE")
        self.assertEqual(a.sync_once()["files_written"], 1)
        imported = b.sync_once()
        self.assertEqual(imported["new_companies"], 1)
        count = len(list(self.shared.glob("*.ldx")))
        b.sync_once()
        self.assertEqual(len(list(self.shared.glob("*.ldx"))), count)
        self.reg_b.save_partner({"name": "Бета", "role": "customer", "inn": "1650987654"})
        b.sync_once()
        a.sync_once()
        self.assertEqual(len(self.reg_a.search()), 2)
        self.assertEqual(len(self.reg_b.search()), 2)
        self.assertEqual(a.sync_once()["files_written"], 0)
        a.close()
        b.close()

    def test_wrong_passphrase_does_not_import(self):
        self.reg_a.save_partner({"name": "Альфа", "role": "carrier"})
        FolderSync(self.reg_a, self.shared, "sync-password-12-SAFE").sync_once()
        bad = FolderSync(self.reg_b, self.shared, "wrong-password-12-X")
        with self.assertRaisesRegex(ValueError, "пароль"):
            bad.sync_once()
        self.assertEqual(self.reg_b.search(), [])


if __name__ == "__main__":
    unittest.main()
