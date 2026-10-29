"""Windows GUI smoke test of the 1.2 preview entrypoint.

Patches to app.py are restored after the test so legacy tests can still
validate original 1.1.3 behaviour independently.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import app
from database import Database


class PreviewSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setStyle("Fusion")

    def test_preview_open_navigation_note_and_dialog_suggestions(self):
        original = (app.LogistWindow, app.RouteDialog, app.CarrierDialog)
        try:
            import app12
            with tempfile.TemporaryDirectory() as directory:
                db = Database(Path(directory) / "preview.db")
                db.save_route({"id": "R001", "origin": "Казань",
                               "destination": "Набережные Челны", "note": "Оригинал"})
                with patch.object(app12.stable_app, "Database", return_value=db):
                    window = app12.LogistWindow12()
                    try:
                        self.assertEqual(window.navigation.count(), 7)
                        window.navigation.setCurrentRow(6)
                        self.assertIs(window.pages.currentWidget(), window.partner_page)
                        window.navigation.setCurrentRow(1)
                        form = app12.RouteDialog12(db)
                        try:
                            self.assertIsNotNone(form.fields["origin"].completer())
                            self.assertGreater(form.fields["origin"].completer().model().rowCount(), 100)
                        finally:
                            form.reject()
                        call = app12.CarrierDialog12(db)
                        try:
                            self.assertIsNotNone(call._drafts)
                        finally:
                            call.reject()
                    finally:
                        window.reminder_timer.stop()
                        window._really_quit = True
                        window.close()
                        self.qt.processEvents()
        finally:
            app.LogistWindow, app.RouteDialog, app.CarrierDialog = original


if __name__ == "__main__":
    unittest.main()
