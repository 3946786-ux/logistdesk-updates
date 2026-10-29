"""Opt-in encrypted contact folder synchronisation for authorized devices.

No network code, account credentials or plaintext files. An externally-synced
folder (e.g. user's own approved OneDrive folder) transports encrypted deltas.
Never replaces the existing trips, database, backup or PIN.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path

from portable_transfer import _dump, export_contacts, import_contacts

MAX_FILES = 1500


class FolderSync:
    def __init__(self, registry, folder: str | Path, passphrase: str,
                 *, include_private: bool = False):
        self.registry = registry
        self.folder = Path(folder)
        if not self.folder.is_dir():
            raise ValueError("Папка синхронизации не найдена")
        self.passphrase = passphrase
        self.include_private = include_private
        # Validate password before changing any state.
        from portable_transfer import _key
        _key(passphrase, b"\0" * 16)
        with registry.con:
            registry.con.execute("""
            CREATE TABLE IF NOT EXISTS synced_contact_files(
                name TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            registry.con.execute("""
            CREATE TABLE IF NOT EXISTS sync_settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")

    def close(self):
        self.passphrase = ""

    def _local_digest(self):
        serialized = json.dumps(_dump(self.registry, self.include_private),
                                ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode()
        return hashlib.sha256(serialized).hexdigest()

    def sync_once(self) -> dict[str, int]:
        if not self.passphrase:
            raise ValueError("Синхронизация отключена")
        if not self.folder.is_dir():
            raise ValueError("Общая папка сейчас недоступна")
        result = {"files_received": 0, "new_companies": 0, "conflicts": 0, "files_written": 0}
        files = sorted(self.folder.glob("LogistDesk_contacts_*.ldx"))
        if len(files) > MAX_FILES:
            raise ValueError("Слишком много файлов. Требуется очистка старых синхронизаций")
        for path in files:
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            done = self.registry.con.execute(
                "SELECT checksum FROM synced_contact_files WHERE name=?", (path.name,)).fetchone()
            if done is not None:
                if done[0] != checksum:
                    raise ValueError("Файл синхронизации изменён после первого импорта")
                continue
            imported = import_contacts(self.registry, path, self.passphrase)
            with self.registry.con:
                self.registry.con.execute(
                    "INSERT INTO synced_contact_files(name,checksum) VALUES(?,?)",
                    (path.name, checksum))
            result["files_received"] += 1
            result["new_companies"] += imported["new_companies"]
            result["conflicts"] += imported["conflicts"]
        digest = self._local_digest()
        prev = self.registry.con.execute(
            "SELECT value FROM sync_settings WHERE key='last_digest'").fetchone()
        if prev is None or prev[0] != digest:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"LogistDesk_contacts_{stamp}_{secrets.token_hex(5)}.ldx"
            target = self.folder / filename
            export_contacts(self.registry, target, self.passphrase,
                            include_private=self.include_private)
            checksum = hashlib.sha256(target.read_bytes()).hexdigest()
            with self.registry.con:
                self.registry.con.execute(
                    "INSERT INTO synced_contact_files(name,checksum) VALUES (?,?)",
                    (filename, checksum))
                self.registry.con.execute(
                    "INSERT INTO sync_settings(key,value) VALUES('last_digest',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (digest,))
            result["files_written"] = 1
        return result
