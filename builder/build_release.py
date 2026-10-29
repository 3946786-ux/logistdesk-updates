"""Create bridge payload, ordinary release ZIP and manifest template from dist/."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from version import APP_VERSION

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
PROGRAM_FILES = [
    "LogistDesk.exe",
    "LogistEmergencyExport.exe",
    "LogistRestore.exe",
]
BRIDGE_FILES = PROGRAM_FILES + ["LogistUpdater.exe", "version.txt", "update_channel.json"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def zip_files(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            src = ROOT / name if name in ("version.txt", "update_channel.json") else DIST / name
            if src.is_file():
                z.write(src, arcname=name)


def main() -> int:
    missing = [name for name in PROGRAM_FILES + ["LogistUpdater.exe"] if not (DIST / name).is_file()]
    if missing:
        raise SystemExit("Missing dist files: " + ", ".join(missing))
    RELEASE.mkdir(exist_ok=True)
    (ROOT / "version.txt").write_text(APP_VERSION + "\n", encoding="utf-8")
    channel = ROOT / "update_channel.json"
    if not channel.exists():
        channel.write_text('{\n  "manifest_url": ""\n}\n', encoding="utf-8")

    payload = ROOT / "release_payload.zip"
    zip_files(payload, BRIDGE_FILES)

    package = RELEASE / f"LogistDesk_{APP_VERSION}_update.zip"
    zip_files(package, PROGRAM_FILES + ["version.txt", "update_channel.json"])
    portable = RELEASE / f"LogistDesk_{APP_VERSION}_portable.zip"
    zip_files(portable, BRIDGE_FILES)
    manifest = {
        "version": APP_VERSION,
        "package_url": package.name,
        "sha256": sha256(package),
        "notes": [
            "Исправлена видимость: «Новый рейс» — фиолетовая, «Новый звонок» — синяя",
            "Исправлена видимость: «Закрыть рейс» — зелёная контрастная кнопка",
            "В карточке рейса раздельные поля «Загрузка» и «Выгрузка»",
            "Вход по 4-значному PIN",
            "Нет блокировки после 5 минут бездействия",
            "Бикотекс: габариты палеты 1.8 × 0.8 × 1.8 м подставляются автоматически",
            "Телефон водителя вынесен в основную форму звонка",
            "Добавлена система автоматических обновлений",
        ],
    }
    (RELEASE / "latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Prepared:", payload)
    print("Prepared:", package)
    print("Prepared:", portable)
    print("Prepared:", RELEASE / "latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
