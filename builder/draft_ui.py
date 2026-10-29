"""Автосохранение незавершённых форм в зашифрованную локальную базу."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

from drafts import DraftStore


def read_value(widget):
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return widget.toPlainText()
    if isinstance(widget, QLineEdit):
        return widget.text()
    return None


def set_value(widget, value):
    if value is None:
        return
    if isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QComboBox):
        widget.setCurrentText(str(value))
    elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
        widget.setPlainText(str(value))
    elif isinstance(widget, QLineEdit) and not widget.isReadOnly():
        widget.setText(str(value))


class DraftController(QObject):
    """При аварии сохраняет данные с небольшой задержкой, при отмене сразу."""

    def __init__(self, dialog, db, form_key, extra=None):
        super().__init__(dialog)
        self.dialog = dialog
        self.key = form_key
        self.store = DraftStore(db)
        self.extra = extra or {}
        self._dirty = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.save)
        self.restore()
        for widget in list(dialog.fields.values()) + list(self.extra.values()):
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.mark_dirty)
            elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
                widget.textChanged.connect(self.mark_dirty)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.mark_dirty)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self.mark_dirty)
        dialog.finished.connect(self.finished)

    def mark_dirty(self, *_):
        self._dirty = True
        self.timer.start()

    def restore(self):
        values = self.store.load(self.key)
        fields = values.get("fields") if isinstance(values, dict) else None
        if isinstance(fields, dict):
            for name, value in fields.items():
                widget = self.dialog.fields.get(name)
                if widget is not None:
                    set_value(widget, value)
        extra = values.get("extra") if isinstance(values, dict) else None
        if isinstance(extra, dict):
            for name, value in extra.items():
                if name == "route_picker" and hasattr(self.dialog, "route"):
                    self.dialog.route.select_route(value)
                else:
                    widget = self.extra.get(name)
                    if widget is not None:
                        set_value(widget, value)

    def values(self):
        extra = {key: read_value(widget) for key, widget in self.extra.items()}
        if hasattr(self.dialog, "route"):
            extra["route_picker"] = self.dialog.route.currentData()
        return {
            "fields": {name: read_value(widget)
                       for name, widget in self.dialog.fields.items()},
            "extra": extra,
        }

    def save(self):
        if self._dirty:
            self.store.save(self.key, self.values())
            self._dirty = False

    def finished(self, result):
        self.timer.stop()
        if result == self.dialog.DialogCode.Accepted:
            self.store.clear(self.key)
        else:
            self.save()
