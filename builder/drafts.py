"""Зашифрованные черновики форм LogistDesk 1.2.

Сохраняются в той же базе, что рейсы и звонки: при включённом SecurityVault
не попадают в незащищённые файлы в AppData и не отправляются в интернет.
"""
from __future__ import annotations

import json
from datetime import datetime


class DraftStore:
    def __init__(self, db):
        self.db = db
        with db.con:
            db.con.execute("""
                CREATE TABLE IF NOT EXISTS form_drafts(
                    form_key TEXT PRIMARY KEY,
                    contents TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def load(self, form_key: str) -> dict:
        row = self.db.con.execute(
            "SELECT contents FROM form_drafts WHERE form_key=?", (form_key,)).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(row[0])
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def save(self, form_key: str, values: dict) -> None:
        if not form_key or not isinstance(values, dict):
            raise ValueError("Некорректный черновик")
        text = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        if len(text) > 100_000:
            raise ValueError("Черновик слишком большой")
        with self.db.con:
            self.db.con.execute("""
                INSERT INTO form_drafts(form_key,contents,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(form_key) DO UPDATE SET
                    contents=excluded.contents,updated_at=excluded.updated_at
                """, (form_key, text, datetime.now().isoformat(timespec="seconds")))

    def clear(self, form_key: str) -> None:
        with self.db.con:
            self.db.con.execute("DELETE FROM form_drafts WHERE form_key=?", (form_key,))
