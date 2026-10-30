"""Readable completion popups for carriers, customers, cities, and route selectors.

QCompleter popups are separate windows. Their natural width can be smaller than
the rendered contact name, especially when Windows text scaling is 125%.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QTimer, Qt
from PySide6.QtWidgets import QApplication, QListView, QStyledItemDelegate, QToolTip


class _FullNameDelegate(QStyledItemDelegate):
    """Keep the entire city or company name visible at 125–200% Windows DPI."""

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        font_height = option.fontMetrics.height()
        # Qt's default completion row can vertically crop large fonts.
        return QSize(hint.width(), max(hint.height(), font_height + 16, 40))

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
        self.view.setSpacing(3)
        self.view.setUniformItemSizes(False)
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
        self.view.setWordWrap(desired > max_width)
        self.view.doItemsLayout()
        # Do not reuse Qt's initial popup height: with a single city match
        # Windows scaling can crop the last line or bottom of the text.
        filtered = self.view.model()
        count = min(
            filtered.rowCount() if filtered is not None else 0,
            self.completer.maxVisibleItems(),
        )
        font_height = self.view.fontMetrics().height()
        heights = [
            max(self.view.sizeHintForRow(row), font_height + 16, 40)
            for row in range(count)
        ]
        max_height = max(72, available.height() - 32)
        target_height = min(max_height, sum(heights) + count * self.view.spacing() + 12)
        if not count:
            target_height = min(max_height, max(44, font_height + 22))
        self.view.resize(target_width, target_height)
        # Keep the complete popup visible, including on a second monitor or
        # when the route dialog is near the bottom/right edge.
        x = min(max(top_left.x(), available.left() + 8),
                available.right() - target_width - 8)
        preferred_y = top_left.y() + self.source.height()
        if preferred_y + target_height > available.bottom() - 6:
            preferred_y = top_left.y() - target_height
        y = min(max(preferred_y, available.top() + 6),
                available.bottom() - target_height - 6)
        self.view.move(x, y)


def make_popup_readable(completer, source):
    """Keep a single sizing controller per popup; returns it for GUI tests."""
    view = completer.popup()
    previous = getattr(view, "_readable_popup", None) if view is not None else None
    if previous is not None:
        return previous
    controller = ReadablePopup(completer, source)
    controller.view._readable_popup = controller
    return controller
