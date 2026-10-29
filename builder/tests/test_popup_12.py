"""Popup geometry regressions: contact names must not be truncated."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QCompleter, QLineEdit

from readable_popup import make_popup_readable
from ui_common import style_combo_popup


class AutocompletePopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_full_company_name_fits_suggestion_popup(self):
        field = QLineEdit()
        field.resize(185, 34)
        full_name = 'ООО «Тестовая транспортно-экспедиционная компания Поволжье»'
        completer = QCompleter([full_name, 'ООО «Тест Транс»'], field)
        field.setCompleter(completer)
        sizer = make_popup_readable(completer, field)
        sizer.fit()
        expected = completer.popup().fontMetrics().horizontalAdvance(full_name) + 48
        available = self.app.primaryScreen().availableGeometry().width() - 24
        self.assertGreaterEqual(completer.popup().width(), min(expected, available))
        self.assertGreaterEqual(completer.popup().width(), field.width())
        self.assertEqual(completer.popup().textElideMode(), Qt.TextElideMode.ElideNone)
        field.deleteLater()

    def test_generic_editable_combobox_is_protected(self):
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(['Рейс R002 Нижнекамск — Санкт-Петербург', 'Рейс R003'])
        style_combo_popup(combo)
        controller = getattr(combo.completer().popup(), '_readable_popup', None)
        self.assertIsNotNone(controller)
        controller.fit()
        self.assertGreaterEqual(combo.completer().popup().width(), combo.width())
        combo.deleteLater()

    def test_popup_is_bounded_by_screen_on_very_long_names(self):
        field = QLineEdit()
        field.resize(150, 30)
        completer = QCompleter(['ООО ' + 'Очень длинное название перевозчика ' * 40], field)
        field.setCompleter(completer)
        make_popup_readable(completer, field).fit()
        available = self.app.primaryScreen().availableGeometry()
        self.assertLessEqual(completer.popup().width(), max(120, available.width() - 24))
        self.assertTrue(completer.popup().wordWrap())
        field.deleteLater()


if __name__ == "__main__":
    unittest.main()
