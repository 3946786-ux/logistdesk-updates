"""Оригиналы подтверждённых документов в защищённой базе LogistDesk.

По умолчанию не сохраняются. Пользователь должен явно выбрать действие.
Работа разрешена только с SecurityVault, чтобы паспорт не попал в открытый
SQLite-файл. Для больших архивов потребуется внешний шифрованный storage.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
KINDS = {
    "partner": "partners",
    "driver": "partner_drivers",
    "vehicle": "partner_vehicles",
}


class DocumentArchive:
    def __init__(self, db):
        if db.vault is None:
            raise ValueError("Хранение оригиналов возможно только в защищённом профиле")
        self.db = db
        tables = {r[0] for r in db.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "document_attachments" not in tables:
            db.backup()
        with db.con:
            db.con.execute("""
                CREATE TABLE IF NOT EXISTS document_attachments(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL CHECK(subject IN ('partner','driver','vehicle')),
                    subject_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    content BLOB NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(subject,subject_id,checksum)
                )
            """)
            db.con.execute("""
                CREATE INDEX IF NOT EXISTS idx_documents_subject
                ON document_attachments(subject,subject_id)
            """)

    def _validate_subject(self, kind: str, item_id: int):
        if kind not in KINDS:
            raise ValueError("Неизвестный тип документа")
        existing = self.db.con.execute(
            f"SELECT 1 FROM {KINDS[kind]} WHERE id=?", (item_id,)).fetchone()
        if not existing:
            raise ValueError("Связанная карточка удалена или не найдена")

    def add(self, kind: str, item_id: int, content: bytes, name: str) -> int:
        self._validate_subject(kind, item_id)
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_DOCUMENT_BYTES:
            raise ValueError("Документ должен иметь размер от 1 байта до 20 МБ")
        total = self.db.con.execute(
            "SELECT COALESCE(SUM(size),0) FROM document_attachments").fetchone()[0]
        digest = hashlib.sha256(content).hexdigest()
        previous = self.db.con.execute(
            "SELECT id FROM document_attachments WHERE subject=? AND subject_id=? AND checksum=?",
            (kind, item_id, digest)).fetchone()
        if previous:
            return int(previous[0])
        if total + len(content) > MAX_ARCHIVE_BYTES:
            raise ValueError("Достигнут лимит защищённого архива (200 МБ)")
        filename = Path(name or "document").name[:150]
        with self.db.con:
            row = self.db.con.execute(
                "INSERT INTO document_attachments(subject,subject_id,filename,checksum,content,size) "
                "VALUES(?,?,?,?,?,?)", (kind, item_id, filename, digest, content, len(content)))
        return int(row.lastrowid)

    def items(self, kind: str, item_id: int) -> list[dict]:
        self._validate_subject(kind, item_id)
        return [dict(x) for x in self.db.con.execute(
            "SELECT id,filename,size,created_at FROM document_attachments "
            "WHERE subject=? AND subject_id=? ORDER BY id DESC", (kind, item_id))]

    def get_bytes(self, doc_id: int) -> bytes:
        record = self.db.con.execute(
            "SELECT content FROM document_attachments WHERE id=?", (doc_id,)).fetchone()
        if not record:
            raise ValueError("Документ не найден")
        return bytes(record[0])

    def delete(self, doc_id: int) -> None:
        with self.db.con:
            self.db.con.execute("DELETE FROM document_attachments WHERE id=?", (doc_id,))
