"""Standalone LogistDesk updater. It never writes to the live database directory except backups/logs."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

ALLOWED_FILES = {"LogistDesk.exe", "LogistEmergencyExport.exe", "LogistRestore.exe", "version.txt", "update_channel.json"}


def data_dir() -> Path:
    custom = os.environ.get("LOGIST_DATA_DIR")
    if custom:
        return Path(custom)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "LogistDesk"
    return Path.home() / ".local" / "share" / "LogistDesk"


def log(message: str) -> None:
    folder = data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    with (folder / "updater.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wait_for_process(pid: int, timeout: float = 45.0) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                try:
                    ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
                    return
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
    end = time.time() + timeout
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.25)


def backup_user_data(version: str) -> None:
    root = data_dir()
    if not root.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = root / "backups" / f"before_update_{version}_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("logist.db", "logist.db.enc", "security.json", "quick_pin.json"):
        src = root / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    log(f"data backup: {dest}")


def safe_extract(package: Path, target: Path) -> None:
    with zipfile.ZipFile(package) as archive:
        names = {Path(name).name for name in archive.namelist() if not name.endswith("/")}
        unexpected = names - ALLOWED_FILES
        required = {"LogistDesk.exe", "LogistEmergencyExport.exe", "LogistRestore.exe"}
        if unexpected or not required.issubset(names):
            raise RuntimeError(f"unexpected update contents: {sorted(unexpected)}")
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if name not in ALLOWED_FILES:
                continue
            with archive.open(info) as source, (target / name).open("wb") as out:
                shutil.copyfileobj(source, out)


def replace_program(install_dir: Path, stage: Path, version: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = data_dir() / "program_backups" / f"before_{version}_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    replaced: list[str] = []
    try:
        for name in ("LogistDesk.exe", "LogistEmergencyExport.exe", "LogistRestore.exe", "version.txt", "update_channel.json"):
            new = stage / name
            if not new.is_file():
                continue
            current = install_dir / name
            if current.is_file():
                shutil.copy2(current, backup / name)
            temp = install_dir / f".{name}.new"
            shutil.copy2(new, temp)
            os.replace(temp, current)
            replaced.append(name)
        log(f"program updated to {version}; files={replaced}")
    except Exception:
        log("update failed; restoring program files")
        for name in replaced:
            old = backup / name
            if old.is_file():
                shutil.copy2(old, install_dir / name)
        raise


def launch(install_dir: Path, launch_name: str) -> None:
    if launch_name.lower().endswith(".py"):
        subprocess.Popen([sys.executable, str(install_dir / launch_name)], cwd=str(install_dir))
    else:
        subprocess.Popen([str(install_dir / launch_name)], cwd=str(install_dir))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--version", required=True)
    parser.add_argument("--launch", default="LogistDesk.exe")
    args = parser.parse_args()
    package = Path(args.package).resolve()
    install_dir = Path(args.install_dir).resolve()
    try:
        if not package.is_file() or sha256(package) != args.sha256.lower():
            raise RuntimeError("package hash mismatch")
        wait_for_process(args.pid)
        backup_user_data(args.version)
        with tempfile.TemporaryDirectory(prefix="logistdesk_update_") as tmp:
            stage = Path(tmp)
            safe_extract(package, stage)
            replace_program(install_dir, stage, args.version)
        package.unlink(missing_ok=True)
        launch(install_dir, args.launch)
        return 0
    except Exception as exc:
        log(f"ERROR: {exc!r}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
