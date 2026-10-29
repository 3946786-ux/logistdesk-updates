"""Optional per-user Windows startup; never require administrator privileges."""
from __future__ import annotations
import os
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "LogistDesk"


def startup_command(project_dir: Path | str) -> str:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if not exe.is_file():
            raise FileNotFoundError("Не найден установленный LogistDesk.exe")
        return f'"{exe}" --minimized'
    root = Path(project_dir).resolve()
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    script = root / "app.py"
    if not pythonw.is_file() or not script.is_file():
        raise FileNotFoundError("Не найден .venv\\Scripts\\pythonw.exe или app.py. Запусти приложение через start_windows.bat.")
    return f'"{pythonw}" "{script}" --minimized'


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, project_dir: Path | str) -> None:
    if os.name != "nt":
        raise OSError("Автозапуск доступен только в Windows")
    import winreg
    if enabled:
        command = startup_command(project_dir)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass
