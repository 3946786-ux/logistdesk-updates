"""Проверки мелких сценариев: города, черновики и восстановление."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QPlainTextEdit, QWidget

from cities import suggest_cities, setup_city_completers
from database import Database
from drafts import DraftStore
from draft_ui import DraftController


class CitiesAndDraftsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "logist.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_cities_offer_known_and_route_values(self):
        self.db.save_route({"id": "R101", "origin": "с. Павловск, Якутия",
                            "destination": "Нерюнгри"})
        result = suggest_cities(self.db)
        self.assertIn("Москва", result)
        self.assertIn("Набережные Челны", result)
        self.assertIn("с. Павловск, Якутия", result)
        self.assertEqual(len(result), len(set(x.casefold().replace("ё", "е") for x in result)))

    def test_completer_both_fields_and_free_input(self):
        class Form:
            fields = {"origin": QLineEdit(), "destination": QLineEdit()}
        form = Form()
        setup_city_completers(form, self.db)
        self.assertIsNotNone(form.fields["origin"].completer())
        self.assertIsNotNone(form.fields["destination"].completer())
        self.assertGreater(form.fields["origin"].completer().model().rowCount(), 100)
        form.fields["origin"].setText("деревня Новая")
        self.assertEqual(form.fields["origin"].text(), "деревня Новая")

    def test_drafts_are_persisted_reopened_and_deleted(self):
        draft = DraftStore(self.db)
        draft.save("new-route", {"fields": {"origin": "Казань", "destination": "Москва"}})
        self.assertEqual(DraftStore(self.db).load("new-route")["fields"]["origin"], "Казань")
        self.db.close()
        self.db = Database(Path(self.tmp.name) / "logist.db")
        self.assertEqual(DraftStore(self.db).load("new-route")["fields"]["destination"], "Москва")
        DraftStore(self.db).clear("new-route")
        self.assertEqual(DraftStore(self.db).load("new-route"), {})


if __name__ == "__main__":
    unittest.main()
