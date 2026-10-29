"""Local account and four-digit PIN dialogs for LogistDesk."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)
from security import SecurityVault, VaultError


class _AuthDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(410)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setObjectName("securityDialog")
        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(26, 26, 26, 25)
        self.layout_main.setSpacing(15)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #f0f5fa")
        self.layout_main.addWidget(heading)
        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color: #b9cadc; font-size: 14px")
        self.layout_main.addWidget(self.description)
        self.fields = QFormLayout()
        self.fields.setVerticalSpacing(13)
        self.fields.setHorizontalSpacing(14)
        self.layout_main.addLayout(self.fields)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #ff9e9e; font-size: 13px")
        self.layout_main.addWidget(self.error)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch()
        self.cancel = QPushButton("Отмена")
        self.cancel.clicked.connect(self.reject)
        self.buttons.addWidget(self.cancel)
        self.accept_button = QPushButton("Войти")
        self.accept_button.setObjectName("primary")
        self.buttons.addWidget(self.accept_button)
        self.layout_main.addLayout(self.buttons)

    def add_secret(self, caption: str, *, pin: bool = False) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setMinimumHeight(38)
        if pin:
            field.setMaxLength(4)
            field.setValidator(QIntValidator(0, 9999, field))
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setPlaceholderText("••••")
        self.fields.addRow(caption, field)
        return field


class CreateAccountDialog(_AuthDialog):
    """Fresh installs use a Windows-bound four-digit PIN; no long password."""
    def __init__(self, vault: SecurityVault, parent=None):
        super().__init__("Первый запуск LogistDesk", parent)
        self.vault = vault
        self.description.setText("Создай короткий PIN для входа на этом компьютере.")
        self.username = QLineEdit()
        self.username.setMinimumHeight(38)
        self.username.setPlaceholderText("Имя")
        self.fields.addRow("Пользователь", self.username)
        self.pin = self.add_secret("PIN", pin=True)
        self.confirm = self.add_secret("Повтори PIN", pin=True)
        self.pin.returnPressed.connect(self._submit)
        self.confirm.returnPressed.connect(self._submit)
        self.accept_button.setText("Сохранить PIN")
        self.accept_button.clicked.connect(self._submit)

    def _submit(self):
        self.accept_button.setEnabled(False)
        try:
            self.vault.setup_pin(self.username.text(), self.pin.text(), self.confirm.text())
        except VaultError as exc:
            self.error.setText(str(exc))
            self.accept_button.setEnabled(True)
            return
        self.pin.clear()
        self.confirm.clear()
        self.accept()


class PinSetupDialog(_AuthDialog):
    """One-time migration from the old long password to a four-digit PIN."""
    def __init__(self, vault: SecurityVault, parent=None):
        super().__init__("Задать короткий PIN", parent)
        self.vault = vault
        self.description.setText("Старый пароль больше не понадобится для обычного входа на этом компьютере.")
        self.pin = self.add_secret("Новый PIN", pin=True)
        self.confirm = self.add_secret("Повтори PIN", pin=True)
        self.accept_button.setText("Сохранить PIN")
        self.accept_button.clicked.connect(self._submit)
        self.pin.returnPressed.connect(self._submit)
        self.confirm.returnPressed.connect(self._submit)

    def _submit(self):
        self.accept_button.setEnabled(False)
        try:
            self.vault.enable_pin(self.pin.text(), self.confirm.text())
        except VaultError as exc:
            self.error.setText(str(exc))
            self.accept_button.setEnabled(True)
            return
        self.pin.clear()
        self.confirm.clear()
        self.accept()


class LoginDialog(_AuthDialog):
    def __init__(self, vault: SecurityVault, *, unlock_only=False, parent=None):
        self.vault = vault
        self.unlock_only = unlock_only
        self.use_pin = vault.pin_configured
        title = "PIN LogistDesk" if self.use_pin else "Вход в LogistDesk"
        super().__init__(title, parent)
        self.failed_attempts = 0
        if self.use_pin:
            self.description.hide()
            self.username = None
            self.secret = self.add_secret("PIN", pin=True)
        else:
            self.description.setText("Один раз введи старый пароль. После входа заменим его на 4-значный PIN.")
            self.username = QLineEdit()
            self.username.setMinimumHeight(38)
            self.username.setText(vault._metadata()["username"])
            self.fields.addRow("Логин", self.username)
            self.secret = self.add_secret("Старый пароль")
        self.secret.returnPressed.connect(self._submit)
        self.accept_button.clicked.connect(self._submit)
        QTimer.singleShot(0, self.secret.setFocus)

    @property
    def password(self):
        """Compatibility with old UI tests/code."""
        return self.secret

    def _submit(self):
        self.accept_button.setEnabled(False)
        try:
            if self.use_pin:
                if self.unlock_only and self.vault._key is not None:
                    if not self.vault.verify_pin(self.secret.text()):
                        raise VaultError("Неверный PIN")
                else:
                    self.vault.unlock_pin(self.secret.text())
            else:
                if self.unlock_only:
                    if not self.vault.verify_password(self.secret.text()):
                        raise VaultError("Неверный пароль")
                else:
                    self.vault.unlock(self.username.text(), self.secret.text())
        except VaultError as exc:
            self.failed_attempts += 1
            self.error.setText(str(exc))
            self.secret.clear()
            if self.failed_attempts >= 5:
                self.error.setText("Слишком много попыток. Повтори через 30 секунд.")
                self.failed_attempts = 0
                QTimer.singleShot(30000, lambda: self.accept_button.setEnabled(True))
            else:
                self.accept_button.setEnabled(True)
            return
        self.secret.clear()
        self.accept()
