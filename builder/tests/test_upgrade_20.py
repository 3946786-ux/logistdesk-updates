"""Critical production upgrade regression: existing encrypted database must survive 2.0."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from drafts import DraftStore
from partner_registry import PartnerRegistry
from security import SecurityVault


class UpgradeFrom113Tests(unittest.TestCase):
    def test_legacy_encrypted_routes_calls_and_pin_remain_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            vault = SecurityVault(path)
            vault.setup_pin("Operator", "2468", "2468")
            db = Database(vault=vault)
            db.save_route({"id": "R081", "origin": "Нижнекамск",
                           "destination": "Казань", "note": "Не терять"})
            carrier_id = db.save_carrier({"route_id": "R081",
                                         "carrier": "ООО Существующий перевозчик",
                                         "phone": "+79991234567",
                                         "desired_rate": 75000})
            db.close()
            before = vault.encrypted_path.read_bytes()
            self.assertNotIn(b"R081", before)

            # Open the same encrypted profile after upgrading the program code.
            reopened = SecurityVault(path)
            reopened.unlock_pin("2468")
            upgraded_db = Database(vault=reopened)
            registry = PartnerRegistry(upgraded_db)
            DraftStore(upgraded_db)
            self.assertEqual(upgraded_db.get_route("R081")["note"], "Не терять")
            self.assertEqual(upgraded_db.get_carrier(carrier_id)["desired_rate"], 75000)
            self.assertEqual(upgraded_db.get_carrier(carrier_id)["phone"], "+79991234567")
            self.assertEqual(registry.search(role="carrier"), [])
            # New fields/tables must not make the old PIN or records unusable.
            upgraded_db.close()
            last = SecurityVault(path)
            last.unlock_pin("2468")
            final_db = Database(vault=last)
            self.assertEqual(final_db.get_route("R081")["origin"], "Нижнекамск")
            final_db.close()
            self.assertTrue(list((path / "backups").glob("*.ldbak")))


if __name__ == "__main__":
    unittest.main()
