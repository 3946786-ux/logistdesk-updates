"""Regression test: draft shelf is visible after maximized startup and can delete drafts."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
import app
from database import Database
from drafts import DraftStore


class DraftShelfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setStyle("Fusion")

    def test_maximized_shelf_and_confirmed_draft_removal(self):
        original = app.LogistWindow, app.RouteDialog, app.CarrierDialog
        try:
            import app12
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(Path(tmp) / "logist.db")
                store = DraftStore(db)
                store.save("new-route:a", {"fields": {
                    "origin": "Казань", "destination": "Уфа"}})
                store.save("new-route:b", {"fields": {
                    "origin": "Нижнекамск", "destination": "Москва"}})
                with patch.object(app12.stable_app, "Database", return_value=db):
                    window = app12.LogistWindow12()
                    try:
                        window.showMaximized()
                        self.qt.processEvents()
                        window._refresh_draft_bar()
                        self.qt.processEvents()
                        window._place_draft_bar()
                        self.assertTrue(window._draft_bar.isVisible())
                        self.assertEqual(window._draft_rows_count, 2)
                        bar = window._draft_bar.geometry()
                        parent = window._draft_host.rect()
                        self.assertGreaterEqual(bar.left(), parent.left())
                        self.assertGreaterEqual(bar.top(), parent.top())
                        self.assertLessEqual(bar.right(), parent.right())
                        self.assertLessEqual(bar.bottom(), parent.bottom())

                        with patch.object(app12.stable_app.QMessageBox, "question",
                                          return_value=QMessageBox.StandardButton.No):
                            window.delete_route_draft("new-route:a")
                        self.assertIn("origin", store.load("new-route:a")["fields"])
                        with patch.object(app12.stable_app.QMessageBox, "question",
                                          return_value=QMessageBox.StandardButton.Yes):
                            window.delete_route_draft("new-route:a")
                        self.assertEqual(store.load("new-route:a"), {})
                        self.assertEqual(window._draft_rows_count, 1)
                        self.assertEqual(store.load("new-route:b")["fields"]["origin"],
                                         "Нижнекамск")

                        window._open_route_draft("new-route:b")
                        self.qt.processEvents()
                        self.assertIn("new-route:b", window._draft_windows)
                        with patch.object(app12.stable_app.QMessageBox, "question",
                                          return_value=QMessageBox.StandardButton.Yes):
                            window.delete_route_draft("new-route:b")
                        self.qt.processEvents()
                        self.assertEqual(store.load("new-route:b"), {})
                        self.assertEqual(window._draft_rows_count, 0)
                        self.assertFalse(window._draft_bar.isVisible())
                    finally:
                        window.reminder_timer.stop()
                        window._really_quit = True
                        window.close()
                        self.qt.processEvents()
                db.close()
        finally:
            app.LogistWindow, app.RouteDialog, app.CarrierDialog = original


if __name__ == "__main__":
    unittest.main()
