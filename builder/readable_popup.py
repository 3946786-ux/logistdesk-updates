"""Readable completion popups for carriers, customers, cities, and route selectors.

QCompleter popups are separate windows. Their natural width can be smaller than
the rendered contact name, especially when Windows text scaling is 125%.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication, QListView, QStyledItemDelegate, QToolTip


class _FullNameDelegate(QStyledItemDelegate):
    def helpEvent(self, event, view, option, index):
        if event.type() == QEvent.Type.ToolTip and index.isValid():
            name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            if name:
                QToolTip.showText(event.globalPos(), name, view)
                return True
        return super().helpEvent(event, view, option, index)


class ReadablePopup(QObject):
    """Fit the popup to names, but never extend beyond the screen boundary."""

    def __init__(self, completer, source):
        super().__init__(completer)
        self.completer = completer
        self.source = source
        self.view = completer.popup()
        if self.view is None:
            # Editable QComboBox may lazily initialize this popup on Windows.
            self.view = QListView(source)
            completer.setPopup(self.view)
        self.view.installEventFilter(self)
        self.view.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setItemDelegate(_FullNameDelegate(self.view))

    def eventFilter(self, watched, event):
        if watched is self.view and event.type() == QEvent.Type.Show:
            QTimer.singleShot(0, self.fit)
        return super().eventFilter(watched, event)

    def fit(self):
        if not self.source or not self.view:
            return
        top_left = self.source.mapToGlobal(QPoint(0, 0))
        screen = QApplication.screenAt(top_left) or self.source.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        max_width = max(120, available.width() - 24)
        model = self.completer.model()
        font = self.view.fontMetrics()
        measured = 0
        if model is not None:
            # Measure the full source string, not just the typed search prefix.
            for row in range(min(model.rowCount(), 2500)):
                label = str(model.index(row, self.completer.completionColumn()).data(
                    Qt.ItemDataRole.DisplayRole) or "")
                measured = max(measured, font.horizontalAdvance(label))
        desired = max(self.source.width(), measured + 48)
        target_width = min(max_width, desired)
        self.view.setMinimumWidth(target_width)
        self.view.setMaximumWidth(max_width)
        self.view.resize(target_width, self.view.height())
        self.view.setWordWrap(desired > max_width)
        self.view.doItemsLayout()
        # A long name near the right edge must stay fully on the monitor.
        x = min(max(top_left.x(), available.left() + 8),
                available.right() - target_width - 8)
        self.view.move(x, self.view.y())


def make_popup_readable(completer, source):
    """Keep a single sizing controller per popup; returns it for GUI tests."""
    view = completer.popup()
    previous = getattr(view, "_readable_popup", None) if view is not None else None
    if previous is not None:
        return previous
    controller = ReadablePopup(completer, source)
    controller.view._readable_popup = controller
    return controller
