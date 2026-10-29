"""Small update client used by the GUI. Network and install steps stay separate."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from version import APP_VERSION


class UpdateError(RuntimeError):
    pass


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        core = value.strip().split("-", 1)[0]
        return tuple(int(part) for part in core.split("."))
    except (ValueError, AttributeError):
        raise UpdateError(f"Некорректная версия обновления: {value!r}")


def manifest_url() -> str:
    override = os.environ.get("LOGIST_UPDATE_MANIFEST_URL", "").strip()
    if override:
        return override
    config = application_dir() / "update_channel.json"
    if not config.is_file():
        return ""
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        return str(data.get("manifest_url") or "").strip()
    except (OSError, ValueError, TypeError):
        return ""


def fetch_manifest(url: str | None = None, *, timeout: float = 20.0) -> dict | None:
    url = (url or manifest_url()).strip()
    if not url:
        return None
    request = urllib.request.Request(url, headers={"User-Agent": f"LogistDesk/{APP_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(256 * 1024)
    except Exception as exc:
        raise UpdateError("Не удалось проверить обновления. Проверь интернет и повтори попытку (ожидание сервера до 20 секунд)") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("Сервер обновлений вернул повреждённый manifest") from exc
    for key in ("version", "package_url", "sha256"):
        if not data.get(key):
            raise UpdateError(f"В manifest обновления нет поля {key}")
    package_url = urllib.parse.urljoin(url, str(data["package_url"]))
    scheme = urllib.parse.urlparse(package_url).scheme.lower()
    # HTTP is allowed only for the explicit local test server.
    if scheme not in ("https", "file") and not (
            scheme == "http" and urllib.parse.urlparse(package_url).hostname in ("127.0.0.1", "localhost")):
        raise UpdateError("Обновление должно скачиваться по HTTPS")
    data["package_url"] = package_url
    data["sha256"] = str(data["sha256"]).lower().strip()
    data["notes"] = [str(x) for x in (data.get("notes") or [])][:20]
    return data


def newer_manifest(url: str | None = None) -> dict | None:
    data = fetch_manifest(url)
    if data is None:
        return None
    return data if _version_tuple(data["version"]) > _version_tuple(APP_VERSION) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_package(manifest: dict, *, timeout: float = 90.0) -> Path:
    version = str(manifest["version"])
    target = Path(tempfile.gettempdir()) / f"LogistDesk_update_{version}.zip"
    request = urllib.request.Request(manifest["package_url"], headers={"User-Agent": f"LogistDesk/{APP_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, target.open("wb") as out:
            total = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > 300 * 1024 * 1024:
                    raise UpdateError("Пакет обновления слишком большой")
                out.write(block)
    except Exception as exc:
        target.unlink(missing_ok=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError("Не удалось скачать обновление") from exc
    if _sha256(target) != manifest["sha256"]:
        target.unlink(missing_ok=True)
        raise UpdateError("Контрольная сумма обновления не совпала. Установка отменена")
    return target


def launch_updater(package: Path, manifest: dict) -> None:
    install_dir = application_dir()
    updater = install_dir / "LogistUpdater.exe"
    if getattr(sys, "frozen", False):
        if not updater.is_file():
            raise UpdateError("LogistUpdater.exe не найден рядом с LogistDesk.exe")
        command = [str(updater)]
    else:
        command = [sys.executable, str(install_dir / "updater.py")]
    command += [
        "--package", str(package),
        "--sha256", str(manifest["sha256"]),
        "--install-dir", str(install_dir),
        "--pid", str(os.getpid()),
        "--version", str(manifest["version"]),
        "--launch", "LogistDesk.exe" if getattr(sys, "frozen", False) else "app.py",
    ]
    try:
        subprocess.Popen(command, cwd=str(install_dir), close_fds=True)
    except OSError as exc:
        raise UpdateError("Не удалось запустить LogistUpdater") from exc
