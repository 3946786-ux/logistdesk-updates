"""Explicit dark popup palettes and Russian confirmation dialogs for PySide6."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox
from theme import POPUP_STYLESHEET


def apply_dark_palette(app: QApplication) -> None:
    palette = app.palette()
    colors = {
        QPalette.ColorRole.Window: "#111820",
        QPalette.ColorRole.WindowText: "#e4ebf2",
        QPalette.ColorRole.Base: "#222f3d",
        QPalette.ColorRole.AlternateBase: "#293848",
        QPalette.ColorRole.Text: "#f0f5fa",
        QPalette.ColorRole.Button: "#263443",
        QPalette.ColorRole.ButtonText: "#e4ebf2",
        QPalette.ColorRole.Highlight: "#3d5b76",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: "#293a4c",
        QPalette.ColorRole.ToolTipText: "#f1f6fa",
        QPalette.ColorRole.PlaceholderText: "#a2b3c4",
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    app.setPalette(palette)


def style_combo_popup(combo) -> None:
    """QCompleter's popup is its own window; parent QSS alone does not style it."""
    if combo.isEditable() and combo.completer() is not None:
        from readable_popup import make_popup_readable
        make_popup_readable(combo.completer(), combo)
    views = [combo.view()]
    if combo.isEditable() and combo.completer() is not None:
        views.append(combo.completer().popup())
    for view in views:
        if view is None:
            continue
        palette = view.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#222f3d"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#f0f5fa"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#3d5b76"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        view.setPalette(palette)
        view.setStyleSheet(POPUP_STYLESHEET)
        view.setAutoFillBackground(True)
        view.viewport().setPalette(palette)
        view.viewport().setStyleSheet("background-color: #222f3d; color: #f0f5fa;")
        view.viewport().setAutoFillBackground(True)


def localized_question(parent, title: str, message: str, *, yes_text="Да", no_text="Отмена") -> bool:
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setWindowTitle(title)
    dialog.setText(message)
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    dialog.button(QMessageBox.StandardButton.Yes).setText(yes_text)
    dialog.button(QMessageBox.StandardButton.No).setText(no_text)
    return dialog.exec() == QMessageBox.StandardButton.Yes


class RussianMessageBox(QMessageBox):
    """Localize standard confirmation and acknowledgement buttons independent of OS locale."""
    @staticmethod
    def question(parent, title, message, buttons=None, defaultButton=None):
        dialog = RussianMessageBox(parent)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setStandardButtons(buttons or (QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No))
        if defaultButton is not None:
            dialog.setDefaultButton(defaultButton)
        labels = {
            QMessageBox.StandardButton.Yes: "Да",
            QMessageBox.StandardButton.No: "Нет",
            QMessageBox.StandardButton.Cancel: "Отмена",
            QMessageBox.StandardButton.Ok: "Понятно",
        }
        for standard, caption in labels.items():
            button = dialog.button(standard)
            if button:
                button.setText(caption)
        return QMessageBox.StandardButton(dialog.exec())

    @staticmethod
    def _message(parent, title, message, icon):
        dialog = RussianMessageBox(parent)
        dialog.setIcon(icon)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText("Понятно")
        return QMessageBox.StandardButton(dialog.exec())

    @staticmethod
    def information(parent, title, message, *args, **kwargs):
        return RussianMessageBox._message(parent, title, message, QMessageBox.Icon.Information)

    @staticmethod
    def warning(parent, title, message, *args, **kwargs):
        return RussianMessageBox._message(parent, title, message, QMessageBox.Icon.Warning)

    @staticmethod
    def critical(parent, title, message, *args, **kwargs):
        return RussianMessageBox._message(parent, title, message, QMessageBox.Icon.Critical)
