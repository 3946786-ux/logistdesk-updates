"""Справочник контрагентов LogistDesk. Данные хранятся в том же защищённом SQLite."""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Mapping


PARTNER_FIELDS = (
    "name", "short_name", "role", "inn", "kpp", "ogrn",
    "legal_address", "actual_address", "bank", "bik", "account",
    "corr_account", "phone", "email", "vat", "payment_terms", "note",
)
DRIVER_FIELDS = (
    "partner_id", "surname", "first_name", "patronymic", "birth_date", "phone",
    "passport_series", "passport_number", "passport_issued", "passport_date",
    "passport_department", "license_number", "license_categories",
    "license_date", "license_expires", "note",
)
VEHICLE_FIELDS = (
    "partner_id", "plate", "vin", "brand", "model", "year",
    "registration_series", "registration_number", "owner", "note",
    "trailer_brand", "trailer_plate", "body_type", "payload_t", "volume_m3",
    "body_length_m", "body_width_m", "body_height_m",
)
VEHICLE_OPTIONAL_COLUMNS = (
    "trailer_brand", "trailer_plate", "body_type", "payload_t", "volume_m3",
    "body_length_m", "body_width_m", "body_height_m",
)
ROLES = frozenset(("carrier", "customer", "both"))


def digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def clean(value: object, limit: int = 1500) -> str:
    return str(value or "").strip()[:limit]


def sql_record(row):
    return dict(row) if row is not None else None


class PartnerRegistry:
    """Использует существующее соединение Database, в том числе EncryptedConnection.

    Таблицы добавляются без изменения таблиц прежних версий. При первом запуске на
    существующей базе создаётся резервная копия её текущего состояния.
    """

    def __init__(self, db):
        self.db = db
        self.con = db.con
        tables = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "routes" in tables and any(name not in tables for name in
            ("partners", "partner_drivers", "partner_vehicles", "partner_routes",
             "driver_vehicle_links", "call_resources")):
            db.backup()
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, short_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'carrier' CHECK(role IN ('carrier','customer','both')),
            inn TEXT NOT NULL DEFAULT '', kpp TEXT NOT NULL DEFAULT '',
            ogrn TEXT NOT NULL DEFAULT '', legal_address TEXT NOT NULL DEFAULT '',
            actual_address TEXT NOT NULL DEFAULT '', bank TEXT NOT NULL DEFAULT '',
            bik TEXT NOT NULL DEFAULT '', account TEXT NOT NULL DEFAULT '',
            corr_account TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '', vat TEXT NOT NULL DEFAULT '',
            payment_terms TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_partners_inn ON partners(inn) WHERE inn <> '';
        CREATE INDEX IF NOT EXISTS idx_partners_name ON partners(name);
        CREATE TABLE IF NOT EXISTS partner_drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER REFERENCES partners(id) ON DELETE SET NULL,
            surname TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            patronymic TEXT NOT NULL DEFAULT '', birth_date TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '', passport_series TEXT NOT NULL DEFAULT '',
            passport_number TEXT NOT NULL DEFAULT '',
            passport_issued TEXT NOT NULL DEFAULT '', passport_date TEXT NOT NULL DEFAULT '',
            passport_department TEXT NOT NULL DEFAULT '',
            license_number TEXT NOT NULL DEFAULT '', license_categories TEXT NOT NULL DEFAULT '',
            license_date TEXT NOT NULL DEFAULT '', license_expires TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_partner_drivers_company ON partner_drivers(partner_id);
        CREATE TABLE IF NOT EXISTS partner_vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER REFERENCES partners(id) ON DELETE SET NULL,
            plate TEXT NOT NULL DEFAULT '', vin TEXT NOT NULL DEFAULT '',
            brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '', registration_series TEXT NOT NULL DEFAULT '',
            registration_number TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_vehicle_vin
            ON partner_vehicles(vin) WHERE vin <> '';
        CREATE INDEX IF NOT EXISTS idx_partner_vehicles_company ON partner_vehicles(partner_id);
        CREATE TABLE IF NOT EXISTS partner_routes (
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            route_id TEXT NOT NULL REFERENCES routes(id),
            role TEXT NOT NULL CHECK(role IN ('carrier','customer')),
            PRIMARY KEY (partner_id,route_id,role)
        );
        CREATE TABLE IF NOT EXISTS driver_vehicle_links (
            driver_id INTEGER NOT NULL REFERENCES partner_drivers(id) ON DELETE CASCADE,
            vehicle_id INTEGER NOT NULL REFERENCES partner_vehicles(id) ON DELETE CASCADE,
            PRIMARY KEY (driver_id,vehicle_id)
        );
        CREATE TABLE IF NOT EXISTS call_resources (
            carrier_call_id INTEGER PRIMARY KEY REFERENCES carriers(id) ON DELETE CASCADE,
            partner_id INTEGER REFERENCES partners(id) ON DELETE SET NULL,
            driver_id INTEGER REFERENCES partner_drivers(id) ON DELETE SET NULL,
            vehicle_id INTEGER REFERENCES partner_vehicles(id) ON DELETE SET NULL
        );
        """)
        existing_cols = {row[1] for row in self.con.execute("PRAGMA table_info(partner_vehicles)")}
        missing = [col for col in VEHICLE_OPTIONAL_COLUMNS if col not in existing_cols]
        if missing:
            # A pre-migration backup is mandatory when modifying a real database.
            if "partner_vehicles" in tables:
                self.db.backup()
            with self.con:
                for col in missing:
                    self.con.execute(f"ALTER TABLE partner_vehicles ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

    def get_partner(self, partner_id: int) -> dict | None:
        return sql_record(self.con.execute(
            "SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone())

    def find_inn(self, inn: str) -> dict | None:
        number = digits(inn)
        if not number:
            return None
        return sql_record(self.con.execute(
            "SELECT * FROM partners WHERE inn=?", (number,)).fetchone())

    def search(self, query: str = "", role: str = "") -> list[dict]:
        query = clean(query, 150)
        sql = "SELECT * FROM partners WHERE 1=1"
        args: list[str] = []
        if role in ("carrier", "customer"):
            sql += " AND role IN (?, 'both')"
            args.append(role)
        if query:
            sql += """ AND (name LIKE ? OR short_name LIKE ? OR inn LIKE ?
                       OR phone LIKE ? OR email LIKE ?)"""
            args.extend([f"%{query}%"] * 5)
        sql += " ORDER BY name COLLATE NOCASE, id LIMIT 500"
        return [dict(row) for row in self.con.execute(sql, args)]

    def save_partner(self, record: Mapping, partner_id: int | None = None) -> int:
        data = {field: clean(record.get(field)) for field in PARTNER_FIELDS}
        data["inn"] = digits(data["inn"])
        data["kpp"] = digits(data["kpp"])
        data["ogrn"] = digits(data["ogrn"])
        data["bik"] = digits(data["bik"])
        data["account"] = digits(data["account"])
        data["corr_account"] = digits(data["corr_account"])
        if not data["name"]:
            raise ValueError("Укажи название организации")
        if data["role"] not in ROLES:
            raise ValueError("Неизвестная роль контрагента")
        if data["inn"] and len(data["inn"]) not in (10, 12):
            raise ValueError("ИНН должен содержать 10 или 12 цифр")
        existing = self.find_inn(data["inn"]) if data["inn"] else None
        if existing and existing["id"] != partner_id:
            raise ValueError("Компания с таким ИНН уже существует: " + existing["name"])
        fields = ", ".join(PARTNER_FIELDS)
        with self.con:
            if partner_id is None:
                values = ", ".join("?" for _ in PARTNER_FIELDS)
                cur = self.con.execute(
                    f"INSERT INTO partners ({fields}) VALUES ({values})",
                    [data[k] for k in PARTNER_FIELDS])
                return int(cur.lastrowid)
            assignments = ", ".join(f"{f}=?" for f in PARTNER_FIELDS)
            cur = self.con.execute(
                f"UPDATE partners SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                [data[k] for k in PARTNER_FIELDS] + [partner_id])
            if cur.rowcount != 1:
                raise ValueError("Контрагент не найден")
            return partner_id

    def _save_child(self, table: str, fields: tuple[str, ...], record: Mapping,
                    record_id: int | None) -> int:
        data = {field: clean(record.get(field)) for field in fields}
        partner_id = record.get("partner_id")
        if partner_id in ("", None):
            data["partner_id"] = None
        else:
            partner_id = int(partner_id)
            if not self.get_partner(partner_id):
                raise ValueError("Контрагент не найден")
            data["partner_id"] = partner_id
        with self.con:
            if record_id is None:
                columns = ",".join(fields)
                placeholders = ",".join("?" for _ in fields)
                cursor = self.con.execute(
                    f"INSERT INTO {table}({columns}) VALUES({placeholders})",
                    [data[k] for k in fields])
                return int(cursor.lastrowid)
            assignments = ",".join(f"{f}=?" for f in fields)
            cursor = self.con.execute(
                f"UPDATE {table} SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                [data[k] for k in fields] + [record_id])
            if cursor.rowcount != 1:
                raise ValueError("Запись не найдена")
        return record_id

    def save_driver(self, record: Mapping, driver_id: int | None = None) -> int:
        if not any(clean(record.get(k)) for k in ("surname", "first_name", "license_number")):
            raise ValueError("Нужны ФИО или номер водительского удостоверения")
        return self._save_child("partner_drivers", DRIVER_FIELDS, record, driver_id)

    def save_vehicle(self, record: Mapping, vehicle_id: int | None = None) -> int:
        if not any(clean(record.get(k)) for k in ("plate", "vin", "brand")):
            raise ValueError("Укажи хотя бы марку или госномер автомобиля")
        vin = clean(record.get("vin")).upper()
        if vin:
            exists = self.con.execute("SELECT id FROM partner_vehicles WHERE vin=?", (vin,)).fetchone()
            if exists and exists[0] != vehicle_id:
                raise ValueError("Автомобиль с таким VIN уже есть в базе")
        data = dict(record)
        data["vin"] = vin
        return self._save_child("partner_vehicles", VEHICLE_FIELDS, data, vehicle_id)

    def drivers(self, partner_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM partner_drivers WHERE partner_id=? ORDER BY surname, first_name",
            (partner_id,))]

    def vehicles(self, partner_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM partner_vehicles WHERE partner_id=? ORDER BY plate, brand",
            (partner_id,))]

    def link_route(self, partner_id: int, route_id: str, role: str) -> None:
        if role not in ("carrier", "customer"):
            raise ValueError("Неверная роль на рейсе")
        with self.con:
            self.con.execute(
                "INSERT OR IGNORE INTO partner_routes(partner_id,route_id,role) VALUES(?,?,?)",
                (partner_id, route_id, role))

    def link_driver_vehicle(self, driver_id: int, vehicle_id: int) -> None:
        driver = self.con.execute(
            "SELECT partner_id FROM partner_drivers WHERE id=?", (driver_id,)).fetchone()
        vehicle = self.con.execute(
            "SELECT partner_id FROM partner_vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if not driver or not vehicle or driver[0] is None or driver[0] != vehicle[0]:
            raise ValueError("Водитель и автомобиль должны принадлежать одному перевозчику")
        with self.con:
            self.con.execute(
                "INSERT OR IGNORE INTO driver_vehicle_links(driver_id,vehicle_id) VALUES (?,?)",
                (driver_id, vehicle_id))

    def vehicles_for_driver(self, driver_id: int) -> list[dict]:
        return [dict(row) for row in self.con.execute(
            "SELECT v.* FROM partner_vehicles v "
            "JOIN driver_vehicle_links dv ON dv.vehicle_id=v.id "
            "WHERE dv.driver_id=? ORDER BY v.plate", (driver_id,))]

    def link_call_resources(self, carrier_call_id: int,
                            partner_id: int | None = None, driver_id: int | None = None,
                            vehicle_id: int | None = None) -> None:
        if partner_id is not None and not self.get_partner(partner_id):
            raise ValueError("Перевозчик из звонка не найден")
        with self.con:
            self.con.execute("""
                INSERT INTO call_resources(carrier_call_id,partner_id,driver_id,vehicle_id)
                VALUES(?,?,?,?)
                ON CONFLICT(carrier_call_id) DO UPDATE SET
                partner_id=excluded.partner_id,driver_id=excluded.driver_id,
                vehicle_id=excluded.vehicle_id
            """, (carrier_call_id, partner_id, driver_id, vehicle_id))
        if driver_id is not None and vehicle_id is not None:
            self.link_driver_vehicle(driver_id, vehicle_id)

    def history(self, partner_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute("""
            SELECT r.*, pr.role AS partner_role FROM partner_routes pr
            JOIN routes r ON r.id=pr.route_id WHERE pr.partner_id=?
            ORDER BY r.created_at DESC
        """, (partner_id,))]

    def delete_driver(self, driver_id: int) -> None:
        row = self.con.execute("SELECT id FROM partner_drivers WHERE id=?", (driver_id,)).fetchone()
        if row is None:
            raise ValueError("Водитель не найден")
        self.db.backup()
        has_docs = self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='document_attachments'").fetchone()
        with self.con:
            if has_docs:
                self.con.execute(
                    "DELETE FROM document_attachments WHERE subject='driver' AND subject_id=?",
                    (driver_id,))
            self.con.execute("DELETE FROM partner_drivers WHERE id=?", (driver_id,))

    def delete_vehicle(self, vehicle_id: int) -> None:
        row = self.con.execute("SELECT id FROM partner_vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if row is None:
            raise ValueError("Автомобиль не найден")
        self.db.backup()
        has_docs = self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='document_attachments'").fetchone()
        with self.con:
            if has_docs:
                self.con.execute(
                    "DELETE FROM document_attachments WHERE subject='vehicle' AND subject_id=?",
                    (vehicle_id,))
            self.con.execute("DELETE FROM partner_vehicles WHERE id=?", (vehicle_id,))

    def delete_partner(self, partner_id: int) -> None:
        if not self.get_partner(partner_id):
            raise ValueError("Контрагент не найден")
        self.db.backup()
        tables = {row[0] for row in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        with self.con:
            if "document_attachments" in tables:
                self.con.execute("""
                    DELETE FROM document_attachments
                    WHERE (subject='partner' AND subject_id=?)
                    OR (subject='driver' AND subject_id IN
                        (SELECT id FROM partner_drivers WHERE partner_id=?))
                    OR (subject='vehicle' AND subject_id IN
                        (SELECT id FROM partner_vehicles WHERE partner_id=?))
                """, (partner_id, partner_id, partner_id))
            if "partner_calls" in tables:
                self.con.execute("DELETE FROM partner_calls WHERE partner_id=?", (partner_id,))
            self.con.execute("DELETE FROM partner_routes WHERE partner_id=?", (partner_id,))
            self.con.execute("DELETE FROM partner_drivers WHERE partner_id=?", (partner_id,))
            self.con.execute("DELETE FROM partner_vehicles WHERE partner_id=?", (partner_id,))
            self.con.execute("DELETE FROM partners WHERE id=?", (partner_id,))

    def expiring_licenses(self, *, within_days: int = 30, today: date | None = None) -> list[dict]:
        """Только реальные даты окончания ВУ, указанные в карточках водителей."""
        today = today or date.today()
        rows = self.con.execute(
            "SELECT d.*,p.name AS company FROM partner_drivers d "
            "LEFT JOIN partners p ON p.id=d.partner_id "
            "WHERE d.license_expires<>''").fetchall()
        results = []
        for row in rows:
            text = str(row["license_expires"]).strip()
            parsed = None
            for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text, fmt).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                continue
            days = (parsed - today).days
            if days <= within_days:
                item = dict(row)
                item["days_left"] = days
                results.append(item)
        return sorted(results, key=lambda item: item["days_left"])
