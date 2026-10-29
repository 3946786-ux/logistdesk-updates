"""One-time bridge updater from pre-1.1 builds to the auto-update capable release."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


def msg(text: str, title: str = "LogistDesk 1.1", flags: int = 0x40) -> int:
    if os.name == "nt":
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    print(text)
    return 1


def data_dir() -> Path:
    custom = os.environ.get("LOGIST_DATA_DIR")
    if custom:
        return Path(custom)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "LogistDesk"


def resource(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def backup_data() -> None:
    root = data_dir()
    if not root.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = root / "backups" / f"before_update_1.1.0_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("logist.db", "logist.db.enc", "security.json", "quick_pin.json"):
        src = root / name
        if src.is_file():
            shutil.copy2(src, dest / name)


def install_payload(target: Path) -> None:
    payload = resource("release_payload.zip")
    if not payload.is_file():
        raise RuntimeError("Внутренний пакет обновления не найден")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    program_backup = data_dir() / "program_backups" / f"bridge_before_1.1.0_{stamp}"
    program_backup.mkdir(parents=True, exist_ok=True)
    names = ("LogistDesk.exe", "LogistEmergencyExport.exe", "LogistRestore.exe",
             "LogistUpdater.exe", "version.txt", "update_channel.json")
    with tempfile.TemporaryDirectory(prefix="logistdesk_bridge_") as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(payload) as archive:
            archive.extractall(stage)
        # Back up every existing program/config file before replacing anything.
        for name in names:
            dst = target / name
            if dst.is_file():
                shutil.copy2(dst, program_backup / name)
        replaced = []
        try:
            for name in names:
                src = stage / name
                if not src.is_file():
                    continue
                dst = target / name
                if name == "update_channel.json" and dst.is_file():
                    # Never erase a channel URL that was already configured.
                    try:
                        if '"manifest_url": ""' not in dst.read_text(encoding="utf-8"):
                            continue
                    except OSError:
                        pass
                temp = target / f".{name}.new"
                shutil.copy2(src, temp)
                os.replace(temp, dst)
                replaced.append(name)
        except Exception:
            for name in replaced:
                old = program_backup / name
                dst = target / name
                if old.is_file():
                    shutil.copy2(old, dst)
                else:
                    dst.unlink(missing_ok=True)
            raise


def main() -> int:
    target = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    # The updater is designed to be copied next to the three current EXEs.
    if not (target / "LogistDesk.exe").is_file():
        msg("Положи LogistDesk_Update_1.1.exe в ту же папку, где находится LogistDesk.exe, и запусти снова.", flags=0x10)
        return 2
    msg("Закрой LogistDesk, если он сейчас открыт.\n\nНажми OK — данные будут сохранены, затем установится версия 1.1.")
    try:
        backup_data()
        install_payload(target)
    except PermissionError:
        msg("Не удалось заменить LogistDesk.exe. Полностью закрой приложение через значок возле часов и запусти обновление ещё раз.", flags=0x10)
        return 3
    except Exception as exc:
        msg(f"Обновление не установлено:\n{exc}", flags=0x10)
        return 4
    try:
        subprocess.Popen([str(target / "LogistDesk.exe")], cwd=str(target))
    except OSError:
        pass
    msg("LogistDesk 1.1 установлен. Рейсы и перевозчики сохранены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
