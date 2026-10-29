"""LogistDesk 2.1 operational sync tests with isolated synthetic databases."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from operations_sync21 import OperationsSync21, _open, _seal


PASSPHRASE = "test-only operations synchronization passphrase"


class OperationsSync21Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.folder = root / "shared"
        self.folder.mkdir()
        self.work = Database(root / "work.db")
        self.home = Database(root / "home.db")
        self.w = OperationsSync21(self.work, self.folder, PASSPHRASE)
        self.h = OperationsSync21(self.home, self.folder, PASSPHRASE)

    def tearDown(self):
        self.w.close()
        self.h.close()
        self.work.close()
        self.home.close()
        self.temp.cleanup()

    def _route(self, db, *, origin="Казань", note=""):
        return db.save_route({
            "id": "R001", "origin": origin, "destination": "Москва",
            "cargo": "Тестовый груз", "status": "Выложен", "note": note,
        })

    def test_route_call_tracking_and_reminder_roundtrip(self):
        self._route(self.work, note="Рабочая заметка")
        cid = self.work.save_carrier({
            "route_id": "R001", "carrier": "Тест Транс",
            "phone": "+7 900 000-00-12", "body": "Тент",
            "driver_name": "Иванов Тест", "status": "Новый",
        })
        with self.work.con:
            self.work.con.execute("""
                INSERT INTO route_tracking(route_id,carrier_id,phase,cycle,driver_name)
                VALUES(?,?,?,?,?)""", ("R001", cid, "В пути", 1, "Иванов Тест"))
            self.work.con.execute("""
                INSERT INTO reminders(route_id,carrier_id,cycle,kind,due_at,state)
                VALUES(?,?,?,?,?,?)""",
                ("R001", cid, 1, "location_unload", "2026-11-01T11:00", "pending"))

        sent = self.w.sync_once()
        self.assertEqual(sent["sent"], 4)
        report = self.h.sync_once()
        self.assertEqual(report["received"], 4)
        self.assertEqual(report["sent"], 0)
        route = self.home.get_route("R001")
        self.assertEqual(route["note"], "Рабочая заметка")
        calls = self.home.carriers(route_id="R001")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["carrier"], "Тест Транс")
        tr = self.home.tracking("R001")
        self.assertEqual(tr["carrier_id"], calls[0]["id"])
        self.assertEqual(tr["phase"], "В пути")
        reminder = self.home.con.execute("SELECT * FROM reminders").fetchone()
        self.assertEqual(reminder["carrier_id"], calls[0]["id"])
        self.assertEqual(reminder["due_at"], "2026-11-01T11:00")
        self.assertEqual(self.h.sync_once()["received"], 0)

        route["note"] = "Заметка из дома"
        self.home.save_route(route)
        self.assertEqual(self.h.sync_once()["sent"], 1)
        self.assertEqual(self.w.sync_once()["received"], 1)
        self.assertEqual(self.work.get_route("R001")["note"], "Заметка из дома")
        self.assertEqual(self.w.sync_once()["sent"], 0)

    def test_equal_native_route_ids_do_not_overwrite(self):
        self._route(self.work, origin="Казань")
        self._route(self.home, origin="Нижнекамск")
        self.assertEqual(self.w.sync_once()["sent"], 1)
        self.assertEqual(self.h.sync_once()["received"], 1)
        # Existing R001 is preserved, different shared identity gets a new native ID.
        rows = self.home.con.execute("SELECT id,origin FROM routes ORDER BY id").fetchall()
        self.assertEqual([(r["id"], r["origin"]) for r in rows],
                         [("R001", "Нижнекамск"), ("R002", "Казань")])
        self.assertEqual(self.w.sync_once()["received"], 1)
        self.assertEqual(self.work.get_route("R001")["origin"], "Казань")
        self.assertEqual(self.work.get_route("R002")["origin"], "Нижнекамск")

    def test_simultaneous_edits_become_conflicts_not_overwrites(self):
        self._route(self.work, note="Оригинал")
        self.w.sync_once()
        self.h.sync_once()
        wr = self.work.get_route("R001")
        hr = self.home.get_route("R001")
        wr["note"] = "Работа изменила"
        hr["note"] = "Дом изменил"
        self.work.save_route(wr)
        self.home.save_route(hr)
        self.assertEqual(self.w.sync_once()["sent"], 1)
        result = self.h.sync_once()
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(self.home.get_route("R001")["note"], "Дом изменил")
        self.assertEqual(self.work.get_route("R001")["note"], "Работа изменила")
        self.assertEqual(
            self.home.con.execute("SELECT COUNT(*) FROM ops21_conflicts").fetchone()[0], 1)

    def test_ciphertext_and_password_validation(self):
        message = {"format": 21, "device": "test", "uid": "a" * 32,
                   "kind": "route", "base": "", "digest": "0" * 64, "value": {}}
        cipher = _seal(message, PASSPHRASE)
        with self.assertRaises(ValueError):
            _open(cipher, "different password with minimum length")
        with self.assertRaises(ValueError):
            _open(cipher, PASSPHRASE)  # malicious/invalid hash rejected


if __name__ == "__main__":
    unittest.main()
