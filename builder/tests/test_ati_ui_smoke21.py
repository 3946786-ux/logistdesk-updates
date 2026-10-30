"""Qt offscreen ATI importer single-cargo preview tests, synthetic text only."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ati_import_ui21 import AtiImportDialog


class FakeDb:
    def __init__(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE routes(id TEXT PRIMARY KEY,origin TEXT,destination TEXT,note TEXT)")
        self.route_number = 0

    def next_route_id(self):
        self.route_number += 1
        return f"R{self.route_number:03d}"

    def save_route(self, payload, replace=False):
        with self.con:
            self.con.execute(
                "INSERT INTO routes VALUES(?,?,?,?)",
                (payload["id"], payload["origin"], payload["destination"], payload["note"]),
            )


class ATIClipboardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_one_load_is_selected_and_adrs_displayed(self):
        db = FakeDb()
        dialog = AtiImportDialog(db)
        dialog.paste.setPlainText("#РХС919191\nКазань → Москва\nADR 8\nUN 1760\n20 т\n180 000 ₽")
        dialog.preview()
        self.assertEqual(1, dialog.table.rowCount())
        self.assertEqual(Qt.CheckState.Checked, dialog.table.item(0, 0).checkState())
        self.assertEqual("8", dialog.table.item(0, 10).text())
        self.assertEqual("1760", dialog.table.item(0, 11).text())
        self.assertEqual("Создать рейс", dialog.create_button.text())
        dialog.close()
        db.con.close()

    def test_many_loads_require_manual_selection(self):
        db = FakeDb()
        dialog = AtiImportDialog(db)
        dialog.paste.setPlainText(
            "#РХС919192\nКазань → Москва\n20 т\n"
            "#РХС919193\nУфа → Пермь\n10 т\n"
        )
        dialog.preview()
        self.assertEqual(2, dialog.table.rowCount())
        self.assertEqual(Qt.CheckState.Unchecked, dialog.table.item(0, 0).checkState())
        self.assertEqual(Qt.CheckState.Unchecked, dialog.table.item(1, 0).checkState())
        self.assertEqual("Создать выбранные рейсы", dialog.create_button.text())
        dialog.close()
        db.con.close()

    def test_already_imported_load_cannot_be_selected_again(self):
        db = FakeDb()
        db.con.execute("CREATE TABLE ati_import21(ati_id TEXT PRIMARY KEY,route_id TEXT NOT NULL UNIQUE,imported_at TEXT)")
        db.con.execute("INSERT INTO ati_import21 VALUES('РХС919194','R001','now')")
        dialog = AtiImportDialog(db)
        dialog.paste.setPlainText("#РХС919194\nКазань → Москва\n20 т")
        dialog.preview()
        item = dialog.table.item(0, 0)
        self.assertEqual(Qt.CheckState.Unchecked, item.checkState())
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsEnabled)
        dialog.close()
        db.con.close()


if __name__ == "__main__":
    unittest.main()
