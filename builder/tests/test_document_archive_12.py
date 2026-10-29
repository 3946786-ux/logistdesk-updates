"""Защищённое хранение оригинала, доступ только после входа в vault."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from document_archive import DocumentArchive
from partner_registry import PartnerRegistry
from security import SecurityVault


class DocumentArchiveTests(unittest.TestCase):
    def test_plain_sqlite_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "plain.db")
            try:
                with self.assertRaisesRegex(ValueError, "защищённом"):
                    DocumentArchive(db)
            finally:
                db.close()

    def test_encrypted_original_stored_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = SecurityVault(Path(directory))
            vault.setup_pin("Test account", "1387", "1387")
            db = Database(vault=vault)
            registry = PartnerRegistry(db)
            company = registry.save_partner({
                "name": "ООО А", "role": "carrier", "inn": "1650123456",
            })
            archive = DocumentArchive(db)
            screenshot = b"\x89PNG\r\n\x1a\n" + b"FAKE_IMAGE_TEST_ONLY_ABC"
            document_id = archive.add("partner", company, screenshot, "screenshot.png")
            self.assertEqual(archive.get_bytes(document_id), screenshot)
            self.assertEqual(len(archive.items("partner", company)), 1)
            encrypted = vault.encrypted_path.read_bytes()
            self.assertNotIn(b"FAKE_IMAGE_TEST_ONLY_ABC", encrypted)
            self.assertEqual(
                archive.add("partner", company, screenshot, "screenshot.png"), document_id)
            archive.delete(document_id)
            self.assertEqual(archive.items("partner", company), [])
            db.close()


if __name__ == "__main__":
    unittest.main()
