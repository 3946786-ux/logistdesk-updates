"""LogistDesk 2.1 explicit, encrypted device-to-device partner exchange.

The storage is an operator-selected, externally synchronized folder, not GitHub.
No passwords, personal documents, partner database, or plaintext index are uploaded.
Nothing is enabled automatically; call close() to discard the session passphrase.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from partner_registry import PartnerRegistry
from portable_transfer import _key, export_contacts, import_contacts
from security import atomic_write

AAD_INDEX = b"LogistDesk/search-index/v21"
MAX_CATALOG_BYTES = 4_000_000
MAX_PENDING_FILES = 2000


def _seal_catalog(payload: dict, phrase: str) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("Каталог слишком большой")
    salt, nonce = os.urandom(16), os.urandom(12)
    enc = AESGCM(_key(phrase, salt)).encrypt(nonce, raw, AAD_INDEX)
    return json.dumps({"format": "LDX21-INDEX", "salt": salt.hex(),
                       "nonce": nonce.hex(), "encrypted": enc.hex()},
                      separators=(",", ":")).encode("ascii")


def _open_catalog(raw: bytes, phrase: str) -> dict:
    if len(raw) > MAX_CATALOG_BYTES * 3:
        raise ValueError("Каталог слишком большой")
    try:
        packet = json.loads(raw)
        if packet.get("format") != "LDX21-INDEX":
            raise ValueError("Неизвестный формат поискового каталога")
        salt = bytes.fromhex(packet["salt"])
        nonce = bytes.fromhex(packet["nonce"])
        ciphertext = bytes.fromhex(packet["encrypted"])
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError("Некорректный каталог")
        result = json.loads(AESGCM(_key(phrase, salt)).decrypt(nonce, ciphertext, AAD_INDEX))
        if result.get("format") != 21 or not isinstance(result.get("entries"), list):
            raise ValueError("Некорректный каталог")
        if len(result["entries"]) > 50000:
            raise ValueError("Слишком много записей")
        allowed = {"name", "role", "inn", "phone", "body_types", "directions"}
        sanitized = []
        for entry in result["entries"]:
            if not isinstance(entry, dict) or not all(isinstance(entry.get(x, ""), str) for x in allowed):
                raise ValueError("Повреждённый каталог")
            sanitized.append({field: entry.get(field, "")[:1500] for field in allowed})
        return {"entries": sanitized}
    except (InvalidTag, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Неверный пароль или повреждённый каталог") from exc


class DeviceExchange21:
    """Private HOME database and transient WORK search catalog.

    No auto-import on work, no reverse contact replication. Transfers must be
    explicitly requested per company; home approves/imports each packet.
    """

    def __init__(self, registry: PartnerRegistry, folder: str | Path,
                 phrase: str, role: str):
        if role not in ("work", "home"):
            raise ValueError("Устройство должно быть «Работа» или «Дом»")
        _key(phrase, b"\\0" * 16)  # Validate before creating directories/DB tables.
        self.registry = registry
        self.folder = Path(folder).resolve(strict=True)
        if not self.folder.is_dir():
            raise ValueError("Выбери существующую общую папку")
        self.phrase = phrase
        self.role = role
        self.root = self.folder / "LogistDesk-Exchange-21"
        self.transfers = self.root / "transfers"
        self.transfers.mkdir(parents=True, exist_ok=True)
        self._catalog_cache: list[dict] = []
        self._catalog_last_digest = ""
        with registry.con:
            registry.con.execute("""CREATE TABLE IF NOT EXISTS exchange21_receipts(
                filename TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

    def close(self) -> None:
        self.phrase = ""
        self._catalog_cache.clear()
        self._catalog_last_digest = ""

    def _check(self):
        if not self.phrase:
            raise ValueError("Обмен отключён")
        if not self.folder.is_dir():
            raise ValueError("Общая папка недоступна")

    def transfer_partner(self, partner_id: int) -> Path:
        """Only selected company and non-sensitive driver/vehicle fields."""
        self._check()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"LD21_transfer_{stamp}_{secrets.token_hex(8)}.ldx"
        dest = self.transfers / filename
        export_contacts(self.registry, dest, self.phrase,
                        include_private=False, partner_ids={partner_id})
        return dest

    def pending_transfers(self) -> list[Path]:
        self._check()
        if self.role != "home":
            return []
        paths = sorted(self.transfers.glob("LD21_transfer_*.ldx"))
        if len(paths) > MAX_PENDING_FILES:
            raise ValueError("Слишком много входящих пакетов; нужен разбор очереди")
        output = []
        for path in paths:
            if path.is_symlink() or not path.is_file():
                continue
            if self.registry.con.execute(
                "SELECT 1 FROM exchange21_receipts WHERE filename=?", (path.name,)
            ).fetchone() is None:
                output.append(path)
        return output

    def import_transfer(self, path: str | Path) -> dict:
        """Only HOME can accept an explicitly chosen inbox transfer."""
        self._check()
        if self.role != "home":
            raise ValueError("Импорт личной базы доступен только дома")
        target = Path(path)
        if target.is_symlink() or target.parent.resolve() != self.transfers.resolve():
            raise ValueError("Файл должен находиться в папке входящих LogistDesk")
        if not target.is_file() or not target.name.startswith("LD21_transfer_") or target.suffix != ".ldx":
            raise ValueError("Неизвестный файл переноса")
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        row = self.registry.con.execute(
            "SELECT sha256 FROM exchange21_receipts WHERE filename=?", (target.name,)
        ).fetchone()
        if row:
            if row[0] != sha:
                raise ValueError("Ранее импортированный файл был изменён")
            return {"already_imported": True, "new_companies": 0,
                    "existing_companies": 0, "drivers": 0, "vehicles": 0, "conflicts": 0}
        report = import_contacts(self.registry, target, self.phrase)
        with self.registry.con:
            self.registry.con.execute(
                "INSERT INTO exchange21_receipts(filename,sha256) VALUES(?,?)",
                (target.name, sha))
        return {"already_imported": False, **report}

    def publish_catalog(self) -> int:
        """Only HOME publishes a minimal search-only index, AES-GCM sealed."""
        self._check()
        if self.role != "home":
            raise ValueError("Публикация личного каталога разрешена только дома")
        rows = [dict(p) for p in self.registry.con.execute(
            "SELECT * FROM partners ORDER BY name LIMIT 50001")]
        if len(rows) > 50000:
            raise ValueError("Слишком много компаний для поискового каталога")
        items = []
        for p in rows:
            if p["role"] not in ("carrier", "both"):
                continue
            vehicles = self.registry.vehicles(p["id"])
            body_types = ", ".join(sorted({
                str(v.get("body_type") or "").strip()
                for v in vehicles if v.get("body_type")}))
            # Summarize historic lanes without leaking rates or route notes.
            lanes = self.registry.con.execute("""
                SELECT DISTINCT r.origin, r.destination
                FROM partner_routes pr JOIN routes r ON r.id=pr.route_id
                WHERE pr.partner_id=? AND pr.role='carrier'
                LIMIT 15""", (p["id"],)).fetchall()
            directions = ", ".join(
                f"{r[0]} → {r[1]}" for r in lanes if r[0] and r[1])
            items.append({
                "name": str(p["name"])[:180], "role": p["role"],
                "inn": str(p["inn"])[:12], "phone": str(p["phone"])[:40],
                "body_types": body_types[:300], "directions": directions[:1200],
            })
        catalog = {"format": 21, "entries": items}
        digest = hashlib.sha256(json.dumps(
            catalog, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if digest != self._catalog_last_digest or not (self.root / "catalog.ldx21").is_file():
            packet = _seal_catalog(catalog, self.phrase)
            atomic_write(self.root / "catalog.ldx21", packet)
            self._catalog_last_digest = digest
        return len(items)

    def refresh_catalog(self) -> int:
        """Decrypt only in process memory; never import into WORK partner DB."""
        self._check()
        path = self.root / "catalog.ldx21"
        if not path.is_file() or path.is_symlink():
            self._catalog_cache.clear()
            return 0
        self._catalog_cache = _open_catalog(path.read_bytes(), self.phrase)["entries"]
        return len(self._catalog_cache)

    def search_catalog(self, query: str) -> list[dict]:
        if self.role != "work":
            raise ValueError("Удалённый поиск предназначен для рабочего ПК")
        needle = query.strip().casefold()
        if not needle:
            return []
        return [dict(row) for row in self._catalog_cache if
                needle in " ".join(row.values()).casefold()][:100]
