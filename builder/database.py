"""SQLite хранится в каталоге пользователя, а не рядом с программой."""
from __future__ import annotations
import os
import sqlite3
import shutil
import csv
from datetime import datetime, timedelta
from pathlib import Path
from rules import route_label
from security import SecurityVault, EncryptedConnection
from tracking import before_arrival, iso_minute, parse_local_datetime, reminder_title

ROUTE_FIELDS = [
    "id", "sender", "origin", "destination", "cargo", "dimensions", "package_type", "places", "weight", "loading",
    "sender_conditions", "own_conditions", "with_vat", "has_without_vat", "manual_without_vat", "date_window", "unload_window", "status", "note",
]
ROUTE_EXTRA_FIELDS = ["carrier_docs_pending", "archived", "deleted_at"]
ROUTE_EXTRA_COLUMNS = {
    "unload_window": "TEXT NOT NULL DEFAULT ''",
    "carrier_docs_pending": "INTEGER NOT NULL DEFAULT 0",
    "archived": "INTEGER NOT NULL DEFAULT 0",
    "deleted_at": "TEXT NOT NULL DEFAULT ''",
}

CARRIER_FIELDS = [
    "route_id", "call_date", "carrier", "phone", "body", "loading", "ready_date", "ready_time", "etrn", "etrn_provider",
    "vat_type", "desired_rate", "payment", "status", "callback_date", "comment", "source_key",
    "markup_percent", "fixed_fee", "personal_percent", "customer_status", "customer_agreed_rate", "customer_vat_type",
    "partial_load", "other_cargo", "hazardous_cargo", "arrival_date", "arrival_time",
    "asked_body", "asked_schedule", "asked_partial", "asked_etrn", "payment_terms_communicated",
    "driver_name", "driver_phone",
]

# Added to an existing 0.4.1 database in place. Never rename or delete old fields.
CARRIER_PRICING_COLUMNS = {
    "markup_percent": "TEXT NOT NULL DEFAULT '15'",
    "fixed_fee": "INTEGER NOT NULL DEFAULT 3000",
    "personal_percent": "TEXT NOT NULL DEFAULT '15'",
    "customer_status": "TEXT NOT NULL DEFAULT 'Не отправлено'",
    "customer_agreed_rate": "INTEGER",
    "customer_vat_type": "TEXT NOT NULL DEFAULT 'Как у перевозчика'",
}

CARRIER_PRICING_DEFAULTS = {
    "markup_percent": "15", "fixed_fee": 3000, "personal_percent": "15",
    "customer_status": "Не отправлено", "customer_agreed_rate": None,
    "customer_vat_type": "Как у перевозчика",
}

CALL_CHECK_FIELDS = (
    "asked_body", "asked_schedule", "asked_partial", "asked_etrn", "payment_terms_communicated",
)
CALL_COLUMNS = {
    "partial_load": "TEXT NOT NULL DEFAULT 'Не уточнено'",
    "other_cargo": "TEXT NOT NULL DEFAULT ''",
    "hazardous_cargo": "TEXT NOT NULL DEFAULT 'Не уточнено'",
    "arrival_date": "TEXT NOT NULL DEFAULT ''",
    "arrival_time": "TEXT NOT NULL DEFAULT ''",
    **{key: "INTEGER NOT NULL DEFAULT 0" for key in CALL_CHECK_FIELDS},
    "driver_name": "TEXT NOT NULL DEFAULT ''",
    "driver_phone": "TEXT NOT NULL DEFAULT ''",
}


def default_data_dir() -> Path:
    custom = os.environ.get("LOGIST_DATA_DIR")
    if custom:
        return Path(custom)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "LogistDesk"
    return Path.home() / ".local" / "share" / "LogistDesk"


class Database:
    def __init__(self, path: Path | str | None = None, *, vault: SecurityVault | None = None):
        self.vault = vault
        self.path = vault.encrypted_path if vault is not None else (Path(path) if path else default_data_dir() / "logist.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = EncryptedConnection(vault) if vault is not None else sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        # Back up the original 0.8 database BEFORE adding any 0.9 schema.
        # The old 0.4/0.5 migration still uses _migrate_carrier_columns below.
        self._migration_backup_made = False
        existing = {row[0] for row in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if "routes" in existing and "carriers" in existing:
            carrier_cols = {row[1] for row in self.con.execute("PRAGMA table_info(carriers)")}
            route_cols = {row[1] for row in self.con.execute("PRAGMA table_info(routes)")}
            needs_update = (any(name not in existing for name in ("route_tracking", "reminders", "route_events"))
                            or any(key not in route_cols for key in ROUTE_EXTRA_COLUMNS)
                            or "driver_phone" not in carrier_cols
                            or any(key not in carrier_cols for key in {**CARRIER_PRICING_COLUMNS, **CALL_COLUMNS}))
            if needs_update:
                self.backup()
                self._migration_backup_made = True
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS routes (
            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT '', destination TEXT NOT NULL DEFAULT '',
            cargo TEXT DEFAULT '', dimensions TEXT DEFAULT '', package_type TEXT DEFAULT '', places TEXT DEFAULT '',
            weight TEXT DEFAULT '', loading TEXT DEFAULT '', sender_conditions TEXT DEFAULT '', own_conditions TEXT DEFAULT '',
            with_vat INTEGER, has_without_vat INTEGER NOT NULL DEFAULT 0, manual_without_vat INTEGER,
            date_window TEXT DEFAULT '', unload_window TEXT NOT NULL DEFAULT '', status TEXT DEFAULT 'Выложен', note TEXT DEFAULT '',
            carrier_docs_pending INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS carriers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL REFERENCES routes(id),
            call_date TEXT DEFAULT '', carrier TEXT DEFAULT '', phone TEXT DEFAULT '', body TEXT DEFAULT '',
            loading TEXT DEFAULT '', ready_date TEXT DEFAULT '', ready_time TEXT DEFAULT '', etrn TEXT DEFAULT '',
            etrn_provider TEXT DEFAULT '', vat_type TEXT DEFAULT '', desired_rate INTEGER, payment TEXT DEFAULT '',
            status TEXT DEFAULT 'Новый', callback_date TEXT DEFAULT '', comment TEXT DEFAULT '',
            source_key TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            markup_percent TEXT NOT NULL DEFAULT '15', fixed_fee INTEGER NOT NULL DEFAULT 3000,
            personal_percent TEXT NOT NULL DEFAULT '15', customer_status TEXT NOT NULL DEFAULT 'Не отправлено',
            customer_agreed_rate INTEGER, customer_vat_type TEXT NOT NULL DEFAULT 'Как у перевозчика',
            partial_load TEXT NOT NULL DEFAULT 'Не уточнено', other_cargo TEXT NOT NULL DEFAULT '',
            hazardous_cargo TEXT NOT NULL DEFAULT 'Не уточнено', arrival_date TEXT NOT NULL DEFAULT '',
            arrival_time TEXT NOT NULL DEFAULT '',
            asked_body INTEGER NOT NULL DEFAULT 0, asked_schedule INTEGER NOT NULL DEFAULT 0,
            asked_partial INTEGER NOT NULL DEFAULT 0, asked_etrn INTEGER NOT NULL DEFAULT 0,
            payment_terms_communicated INTEGER NOT NULL DEFAULT 0,
            driver_name TEXT NOT NULL DEFAULT '', driver_phone TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_carriers_phone ON carriers(phone);
        CREATE INDEX IF NOT EXISTS idx_carriers_route ON carriers(route_id);
        """)
        self.con.commit()
        self._migrate_route_columns()
        self._migrate_carrier_columns()
        self._init_tracking_tables()
        # Old active status names map to the new, user-approved wording.
        with self.con:
            self.con.execute("UPDATE routes SET status='Выложен' WHERE status IN ('Открыт','Размещён','Ищем машину')")

    def _migrate_route_columns(self):
        columns = {row["name"] for row in self.con.execute("PRAGMA table_info(routes)")}
        missing = {key: definition for key, definition in ROUTE_EXTRA_COLUMNS.items() if key not in columns}
        if not missing:
            return
        if not self._migration_backup_made:
            self.backup()
            self._migration_backup_made = True
        with self.con:
            for key, definition in missing.items():
                self.con.execute(f"ALTER TABLE routes ADD COLUMN {key} {definition}")

    def _migrate_carrier_columns(self):
        columns = {row["name"] for row in self.con.execute("PRAGMA table_info(carriers)")}
        required = {**CARRIER_PRICING_COLUMNS, **CALL_COLUMNS}
        missing = {name: sql_type for name, sql_type in required.items() if name not in columns}
        if not missing:
            return
        # A single consistent SQLite backup BEFORE migrating either 0.4.1 or 0.5.
        if not self._migration_backup_made:
            self.backup()
            self._migration_backup_made = True
        with self.con:
            for name, sql_type in missing.items():
                self.con.execute(f"ALTER TABLE carriers ADD COLUMN {name} {sql_type}")

    def _init_tracking_tables(self):
        with self.con:
            self.con.executescript("""
            CREATE TABLE IF NOT EXISTS route_tracking (
                route_id TEXT PRIMARY KEY REFERENCES routes(id),
                carrier_id INTEGER REFERENCES carriers(id) ON DELETE SET NULL,
                driver_name TEXT NOT NULL DEFAULT '', driver_phone TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT 'Пауза', cycle INTEGER NOT NULL DEFAULT 0,
                load_due_at TEXT NOT NULL DEFAULT '', unload_due_at TEXT NOT NULL DEFAULT '',
                photos_received INTEGER NOT NULL DEFAULT 0,
                signed_docs_received INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id TEXT NOT NULL REFERENCES routes(id),
                carrier_id INTEGER REFERENCES carriers(id) ON DELETE SET NULL,
                cycle INTEGER NOT NULL, kind TEXT NOT NULL,
                due_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(route_id, cycle, kind)
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(state, due_at);
            CREATE TABLE IF NOT EXISTS route_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id TEXT NOT NULL REFERENCES routes(id),
                carrier_id INTEGER REFERENCES carriers(id) ON DELETE SET NULL,
                happened_at TEXT NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_route_events ON route_events(route_id, id);
            """)

    def close(self):
        self.con.close()

    def next_route_id(self) -> str:
        ids = self.con.execute("SELECT id FROM routes WHERE id GLOB 'R[0-9]*'").fetchall()
        maximum = max((int(x["id"][1:]) for x in ids if x["id"][1:].isdigit()), default=0)
        return f"R{maximum + 1:03d}"

    def routes(self, search: str = "", include_closed: bool = True,
               include_archived: bool = False, *, deleted_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM routes WHERE 1=1"
        args = []
        if deleted_only:
            sql += " AND deleted_at<>''"
        else:
            sql += " AND deleted_at=''"
        if not include_archived and not deleted_only:
            sql += " AND archived=0"
        if not include_closed and not deleted_only:
            sql += " AND status NOT IN ('Закрыт','Отменён')"
        if search.strip():
            sql += " AND (id LIKE ? OR origin LIKE ? OR destination LIKE ? OR sender LIKE ? OR cargo LIKE ?)"
            args = [f"%{search.strip()}%"] * 5
        sql += " ORDER BY created_at DESC, id DESC"
        return [dict(x) for x in self.con.execute(sql, args).fetchall()]

    def get_route(self, route_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM routes WHERE id = ?", (route_id,)).fetchone()
        return dict(row) if row else None

    def save_route(self, record: dict, *, replace: bool = True) -> str:
        route_id = str(record.get("id") or self.next_route_id()).strip().upper()
        if not route_id:
            raise ValueError("Не указан ID рейса")
        data = {k: record.get(k) for k in ROUTE_FIELDS}
        data["id"] = route_id
        for k in ROUTE_FIELDS:
            if data[k] is None and k not in ("with_vat", "manual_without_vat"):
                data[k] = 0 if k == "has_without_vat" else ""
        data["has_without_vat"] = int(bool(data["has_without_vat"]))
        if not data["status"] or data["status"] in ("Открыт", "Размещён", "Ищем машину"):
            data["status"] = "Выложен"
        cols = ",".join(ROUTE_FIELDS)
        marks = ",".join("?" for _ in ROUTE_FIELDS)
        if replace:
            updates = ",".join(f"{x}=excluded.{x}" for x in ROUTE_FIELDS if x != "id")
            sql = f"INSERT INTO routes({cols}) VALUES ({marks}) ON CONFLICT(id) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP"
        else:
            sql = f"INSERT OR IGNORE INTO routes({cols}) VALUES ({marks})"
        with self.con:
            self.con.execute(sql, [data[k] for k in ROUTE_FIELDS])
        return route_id

    def set_carrier_documents(self, route_id: str, pending: bool, *, now=None) -> None:
        route = self.get_route(route_id)
        if not route:
            raise ValueError("Рейс не найден")
        if route["archived"]:
            raise ValueError("Сначала верни рейс из архива")
        if bool(route["carrier_docs_pending"]) == bool(pending):
            return
        with self.con:
            self.con.execute("UPDATE routes SET carrier_docs_pending=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (int(bool(pending)), route_id))
            self._event(route_id, None, "Жду документы перевозчика" if pending
                        else "Документы перевозчика получены", now=now)

    def archive_route(self, route_id: str, *, archive: bool = True, now=None) -> None:
        route = self.get_route(route_id)
        if not route:
            raise ValueError("Рейс не найден")
        if bool(route["archived"]) == bool(archive):
            return
        tracking = self.tracking(route_id)
        if archive and tracking and tracking["phase"] not in ("Завершён", "Пауза"):
            raise ValueError("Рейс ещё сопровождается. Сначала заверши контроль перевозки и документы.")
        with self.con:
            self.con.execute("UPDATE routes SET archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (int(bool(archive)), route_id))
            self._event(route_id, None, "Рейс перемещён в архив" if archive
                        else "Рейс возвращён из архива", now=now)

    def move_route_to_trash(self, route_id: str, *, now=None) -> None:
        """Reversible deletion. Pending reminders stop, but history and carrier records survive."""
        route = self.get_route(route_id)
        if not route:
            raise ValueError("Рейс не найден")
        if route["deleted_at"]:
            return
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        with self.con:
            self._event(route_id, None, "Рейс перемещён в корзину", now=now)
            self.con.execute("UPDATE reminders SET state='canceled',updated_at=CURRENT_TIMESTAMP "
                             "WHERE route_id=? AND state='pending'", (route_id,))
            self.con.execute("UPDATE route_tracking SET phase='Пауза',updated_at=CURRENT_TIMESTAMP "
                             "WHERE route_id=?", (route_id,))
            self.con.execute("UPDATE routes SET deleted_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (stamp, route_id))

    def restore_route(self, route_id: str, *, now=None) -> None:
        route = self.get_route(route_id)
        if not route:
            raise ValueError("Рейс не найден")
        if not route["deleted_at"]:
            return
        with self.con:
            self.con.execute("UPDATE routes SET deleted_at='',updated_at=CURRENT_TIMESTAMP WHERE id=?", (route_id,))
            self._event(route_id, None, "Рейс восстановлен из корзины", now=now)

    def carriers(self, search: str = "", route_id: str | None = None) -> list[dict]:
        sql = "SELECT c.*, r.origin, r.destination, r.weight, r.places, r.package_type FROM carriers c JOIN routes r ON r.id=c.route_id WHERE r.deleted_at=''"
        args = []
        if route_id:
            sql += " AND c.route_id=?"
            args.append(route_id)
        if search.strip():
            sql += " AND (c.phone LIKE ? OR c.carrier LIKE ? OR r.origin LIKE ? OR r.destination LIKE ? OR c.route_id LIKE ?)"
            args += [f"%{search.strip()}%"] * 5
        sql += " ORDER BY c.id DESC"
        out = [dict(x) for x in self.con.execute(sql, args)]
        for c in out:
            c["route_label"] = route_label({**c, "id": c["route_id"]})
        return out

    def get_carrier(self, carrier_id: int) -> dict | None:
        row = self.con.execute("SELECT * FROM carriers WHERE id=?", (carrier_id,)).fetchone()
        return dict(row) if row else None

    def save_carrier(self, record: dict, carrier_id: int | None = None, *, ignore_duplicates: bool = False) -> int:
        data = {k: record.get(k) for k in CARRIER_FIELDS}
        if not self.get_route(str(data["route_id"] or "")):
            raise ValueError("Сначала выбери существующий рейс")
        for k in CARRIER_FIELDS:
            if data[k] is None and k != "desired_rate" and k != "source_key":
                data[k] = ""
        for key, default in CARRIER_PRICING_DEFAULTS.items():
            if key not in record or record[key] in (None, ""):
                data[key] = default
        for key in ("partial_load", "hazardous_cargo"):
            if not data[key]:
                data[key] = "Не уточнено"
        for key in CALL_CHECK_FIELDS:
            raw = data[key]
            data[key] = int(raw is True or str(raw).strip().lower() in ("1", "true", "да"))
        from rules import parse_money, parse_percent, quote_calculation
        data["desired_rate"] = parse_money(data["desired_rate"])
        data["customer_agreed_rate"] = parse_money(data["customer_agreed_rate"])
        data["fixed_fee"] = parse_money(data["fixed_fee"])
        data["markup_percent"] = str(parse_percent(data["markup_percent"], maximum=1000))
        data["personal_percent"] = str(parse_percent(data["personal_percent"]))
        if data["customer_status"] == "Согласовано" and data["customer_agreed_rate"] is None:
            raise ValueError("Укажи подтверждённую заказчиком ставку")
        quote_calculation(data)  # Validate rates and prevent negative amounts.
        with self.con:
            if carrier_id is not None:
                fields = [k for k in CARRIER_FIELDS if k != "source_key"]
                self.con.execute(
                    "UPDATE carriers SET " + ",".join(f"{k}=?" for k in fields) + ",updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    [data[k] for k in fields] + [carrier_id],
                )
                # Edits to a driver's phone must immediately reach notifications.
                self.con.execute("""UPDATE route_tracking SET driver_name=?,driver_phone=?,updated_at=CURRENT_TIMESTAMP
                    WHERE carrier_id=? AND phase NOT IN ('Пауза','Завершён')""",
                    (data["driver_name"], data["driver_phone"], carrier_id),
                )
                return carrier_id
            verb = "INSERT OR IGNORE" if ignore_duplicates else "INSERT"
            cur = self.con.execute(
                f"{verb} INTO carriers({','.join(CARRIER_FIELDS)}) VALUES ({','.join('?' for _ in CARRIER_FIELDS)})",
                [data[k] for k in CARRIER_FIELDS],
            )
            return cur.lastrowid or 0

    def phone_history(self, phone: str, *, exclude_id: int | None = None) -> list[dict]:
        """All earlier calls from the same normalized phone, across routes."""
        from rules import normalize_phone
        normalized = normalize_phone(phone)
        if not normalized:
            return []
        return [c for c in self.carriers() if normalize_phone(c.get("phone")) == normalized
                and (exclude_id is None or c["id"] != exclude_id)]

    def delete_carrier(self, carrier_id: int) -> None:
        """Remove a call safely; an active transport must first be reopened."""
        carrier = self.get_carrier(carrier_id)
        if carrier is None:
            raise ValueError("Машина не найдена")
        tracking = self.tracking(carrier["route_id"])
        if tracking and tracking["carrier_id"] == carrier_id and tracking["phase"] not in ("Пауза", "Завершён"):
            raise ValueError("Эта машина сейчас выполняет рейс. Сначала верни рейс в «Выложен».")
        with self.con:
            self.con.execute("DELETE FROM carriers WHERE id=?", (carrier_id,))

    def tracking(self, route_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM route_tracking WHERE route_id=?", (route_id,)).fetchone()
        return dict(row) if row else None

    def _event(self, route_id: str, carrier_id: int | None, event: str, details: str = "", *, now=None):
        when = (now or datetime.now()).isoformat(timespec="seconds")
        self.con.execute(
            "INSERT INTO route_events(route_id,carrier_id,happened_at,event,details) VALUES (?,?,?,?,?)",
            (route_id, carrier_id, when, event, details),
        )

    def _reminder(self, route_id: str, carrier_id: int, cycle: int, kind: str, due_at: str):
        self.con.execute("""INSERT INTO reminders(route_id,carrier_id,cycle,kind,due_at,state)
            VALUES (?,?,?,?,?,'pending')
            ON CONFLICT(route_id,cycle,kind) DO UPDATE SET
                due_at=excluded.due_at,state='pending',updated_at=CURRENT_TIMESTAMP""",
            (route_id, carrier_id, cycle, kind, iso_minute(due_at)),
        )

    def close_route(self, route_id: str, carrier_id: int, load_due_at: str = "",
                    driver_name: str = "", driver_phone: str = "", *, now=None) -> None:
        route = self.get_route(route_id)
        carrier = self.get_carrier(carrier_id)
        if not route or not carrier or carrier["route_id"] != route_id:
            raise ValueError("Выбери машину, записанную по этому рейсу")
        if route["archived"]:
            raise ValueError("Сначала верни рейс из архива")
        previous = self.tracking(route_id)
        if route["status"] == "Закрыт":
            raise ValueError("Рейс уже закрыт. Измени этап в разделе «Сегодня» или верни рейс в «Выложен».")
        now = now or datetime.now()
        eta = iso_minute(load_due_at) if str(load_due_at or "").strip() else ""
        cycle = (previous["cycle"] if previous else 0) + 1
        name = driver_name.strip() or carrier.get("driver_name") or ""
        phone = driver_phone.strip() or carrier.get("driver_phone") or ""
        with self.con:
            self.con.execute("UPDATE reminders SET state='canceled' WHERE route_id=? AND state='pending'", (route_id,))
            self.con.execute("UPDATE routes SET status='Закрыт',updated_at=CURRENT_TIMESTAMP WHERE id=?", (route_id,))
            self.con.execute("UPDATE carriers SET status='Согласован',driver_name=?,driver_phone=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (name, phone, carrier_id))
            self.con.execute("""INSERT INTO route_tracking
                (route_id,carrier_id,driver_name,driver_phone,phase,cycle,load_due_at,unload_due_at,photos_received,signed_docs_received)
                VALUES (?,?,?,?,'К загрузке',?,?, '',0,0)
                ON CONFLICT(route_id) DO UPDATE SET
                carrier_id=excluded.carrier_id,driver_name=excluded.driver_name,driver_phone=excluded.driver_phone,
                phase=excluded.phase,cycle=excluded.cycle,load_due_at=excluded.load_due_at,
                unload_due_at='',photos_received=0,signed_docs_received=0,updated_at=CURRENT_TIMESTAMP""",
                (route_id, carrier_id, name, phone, cycle, eta),
            )
            if eta:
                self._reminder(route_id, carrier_id, cycle, "location_load", before_arrival(eta, now=now))
                self._reminder(route_id, carrier_id, cycle, "loading", eta)
            self._event(route_id, carrier_id, "Рейс закрыт — машина согласована",
                        f"Загрузка: {eta or 'время пока не указано'}; "
                        f"водитель: {name or 'не указан'}; телефон: {phone or 'не указан'}", now=now)

    def set_driver_phone(self, route_id: str, phone: str, *, now=None) -> None:
        t = self.tracking(route_id)
        if not t or t["carrier_id"] is None or t["phase"] in ("Пауза", "Завершён"):
            raise ValueError("Номер водителя можно изменить только для активной перевозки")
        number = str(phone or "").strip()
        with self.con:
            self.con.execute("UPDATE route_tracking SET driver_phone=?,updated_at=CURRENT_TIMESTAMP WHERE route_id=?",
                             (number, route_id))
            self.con.execute("UPDATE carriers SET driver_phone=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (number, t["carrier_id"]))
            self._event(route_id, t["carrier_id"], "Контакт водителя обновлён", now=now)

    def reopen_route(self, route_id: str, *, now=None) -> None:
        route = self.get_route(route_id)
        if not route:
            raise ValueError("Рейс не найден")
        with self.con:
            self.con.execute("UPDATE routes SET status='Выложен',updated_at=CURRENT_TIMESTAMP WHERE id=?", (route_id,))
            self.con.execute("UPDATE route_tracking SET phase='Пауза',updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (route_id,))
            self.con.execute("UPDATE reminders SET state='canceled',updated_at=CURRENT_TIMESTAMP WHERE route_id=? AND state='pending'", (route_id,))
            self._event(route_id, None, "Рейс снова выложен", now=now)

    def delay_loading(self, route_id: str, new_eta: str, *, now=None) -> None:
        t = self.tracking(route_id)
        if not t or t["phase"] != "К загрузке" or t["carrier_id"] is None:
            raise ValueError("Изменить время загрузки можно только до её подтверждения")
        eta = iso_minute(new_eta)
        now = now or datetime.now()
        with self.con:
            self.con.execute("UPDATE route_tracking SET load_due_at=?,updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (eta, route_id))
            self.con.execute("""UPDATE reminders SET due_at=?,updated_at=CURRENT_TIMESTAMP
                WHERE route_id=? AND cycle=? AND kind='loading' AND state='pending'""",
                (eta, route_id, t["cycle"]),
            )
            self.con.execute("""UPDATE reminders SET due_at=?,updated_at=CURRENT_TIMESTAMP
                WHERE route_id=? AND cycle=? AND kind='location_load' AND state='pending'""",
                (before_arrival(eta, now=now), route_id, t["cycle"]),
            )
            if not t["load_due_at"]:
                self._reminder(route_id, t["carrier_id"], t["cycle"], "location_load", before_arrival(eta, now=now))
                self._reminder(route_id, t["carrier_id"], t["cycle"], "loading", eta)
            self._event(route_id, t["carrier_id"],
                        "Время загрузки назначено" if not t["load_due_at"] else "Загрузка перенесена", eta, now=now)

    def confirm_loaded(self, route_id: str, unload_due_at: str | None = None, *, now=None) -> None:
        t = self.tracking(route_id)
        if not t or t["phase"] != "К загрузке" or t["carrier_id"] is None:
            raise ValueError("Рейс уже загружен или не находится на контроле")
        now = now or datetime.now()
        with self.con:
            self.con.execute("UPDATE route_tracking SET phase='В пути',updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (route_id,))
            self.con.execute("""UPDATE reminders SET state='done',updated_at=CURRENT_TIMESTAMP
                WHERE route_id=? AND cycle=? AND kind IN ('location_load','loading') AND state='pending'""",
                (route_id, t["cycle"]),
            )
            self._reminder(route_id, t["carrier_id"], t["cycle"], "photos", now.isoformat(timespec="minutes"))
            self._event(route_id, t["carrier_id"], "Водитель загрузился", now=now)
            if unload_due_at:
                self._set_unload_eta(route_id, t["carrier_id"], t["cycle"], unload_due_at, now=now)
            else:
                self._reminder(route_id, t["carrier_id"], t["cycle"], "unload_eta",
                               (now + timedelta(minutes=30)).isoformat(timespec="minutes"))

    def _set_unload_eta(self, route_id: str, carrier_id: int, cycle: int, eta: str, *, now):
        due = iso_minute(eta)
        self.con.execute("UPDATE route_tracking SET unload_due_at=?,updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (due, route_id))
        self.con.execute("""UPDATE reminders SET state='done',updated_at=CURRENT_TIMESTAMP
            WHERE route_id=? AND cycle=? AND kind='unload_eta' AND state='pending'""", (route_id, cycle))
        self._reminder(route_id, carrier_id, cycle, "location_unload", before_arrival(due, now=now))
        self._reminder(route_id, carrier_id, cycle, "unloading", due)
        self._event(route_id, carrier_id, "Выгрузка запланирована", due, now=now)

    def set_unload_eta(self, route_id: str, eta: str, *, now=None):
        t = self.tracking(route_id)
        if not t or t["phase"] != "В пути" or t["carrier_id"] is None:
            raise ValueError("Указать выгрузку можно только для машины в пути")
        with self.con:
            self._set_unload_eta(route_id, t["carrier_id"], t["cycle"], eta, now=now or datetime.now())

    def confirm_unloaded(self, route_id: str, *, now=None):
        t = self.tracking(route_id)
        if not t or t["phase"] != "В пути" or t["carrier_id"] is None:
            raise ValueError("Выгрузку можно подтвердить только для машины в пути")
        now = now or datetime.now()
        with self.con:
            self.con.execute("UPDATE route_tracking SET phase='Выгружен',updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (route_id,))
            self.con.execute("""UPDATE reminders SET state='done',updated_at=CURRENT_TIMESTAMP
                WHERE route_id=? AND cycle=? AND kind IN ('location_unload','unloading','unload_eta') AND state='pending'""",
                (route_id, t["cycle"]),
            )
            self._reminder(route_id, t["carrier_id"], t["cycle"], "signed_docs", now.isoformat(timespec="minutes"))
            self._event(route_id, t["carrier_id"], "Водитель выгрузился", now=now)

    def receive_photos(self, route_id: str, *, now=None):
        t = self.tracking(route_id)
        if not t or t["phase"] not in ("В пути", "Выгружен", "Завершён"):
            raise ValueError("Фотографии отмечаются после загрузки")
        if t["photos_received"]:
            return
        with self.con:
            self.con.execute("UPDATE route_tracking SET photos_received=1,updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (route_id,))
            self.con.execute("""UPDATE reminders SET state='done',updated_at=CURRENT_TIMESTAMP
                WHERE route_id=? AND cycle=? AND kind='photos' AND state='pending'""", (route_id, t["cycle"]))
            if t["signed_docs_received"] and t["phase"] == "Выгружен":
                self.con.execute("UPDATE route_tracking SET phase='Завершён' WHERE route_id=?", (route_id,))
            self._event(route_id, t["carrier_id"], "Фотографии документов получены", now=now)

    def receive_signed_docs(self, route_id: str, *, now=None):
        t = self.tracking(route_id)
        if not t or t["phase"] not in ("Выгружен", "Завершён"):
            raise ValueError("Подписанные документы отмечаются после выгрузки")
        if t["signed_docs_received"]:
            return
        with self.con:
            self.con.execute("UPDATE route_tracking SET signed_docs_received=1,updated_at=CURRENT_TIMESTAMP WHERE route_id=?", (route_id,))
            self.con.execute("""UPDATE reminders SET state='done',updated_at=CURRENT_TIMESTAMP
                WHERE route_id=? AND cycle=? AND kind='signed_docs' AND state='pending'""", (route_id, t["cycle"]))
            if t["photos_received"]:
                self.con.execute("UPDATE route_tracking SET phase='Завершён' WHERE route_id=?", (route_id,))
            self._event(route_id, t["carrier_id"], "Подписанные документы получены", now=now)

    def reminder(self, reminder_id: int) -> dict | None:
        row = self.con.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        return dict(row) if row else None

    def complete_reminder(self, reminder_id: int, *, now=None) -> None:
        r = self.reminder(reminder_id)
        if not r or r["state"] != "pending":
            raise ValueError("Напоминание уже обработано или не найдено")
        if r["kind"] not in ("location_load", "location_unload"):
            raise ValueError("Для этого этапа используй соответствующую кнопку подтверждения")
        with self.con:
            self.con.execute("UPDATE reminders SET state='done',updated_at=CURRENT_TIMESTAMP WHERE id=?", (reminder_id,))
            self._event(r["route_id"], r["carrier_id"], "Звонок выполнен", reminder_title(r["kind"]), now=now)

    def snooze_reminder(self, reminder_id: int, *, minutes=30, now=None) -> None:
        r = self.reminder(reminder_id)
        if not r or r["state"] != "pending":
            raise ValueError("Напоминание уже обработано или не найдено")
        if minutes < 1 or minutes > 10080:
            raise ValueError("Перенос должен быть от 1 минуты до 7 дней")
        when = (now or datetime.now()) + timedelta(minutes=minutes)
        with self.con:
            self.con.execute("UPDATE reminders SET due_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (when.isoformat(timespec="minutes"), reminder_id))
            self._event(r["route_id"], r["carrier_id"], "Напоминание отложено",
                        f"{reminder_title(r['kind'])}: на {minutes} мин", now=now)

    def reschedule_reminder(self, reminder_id: int, new_due_at: str, *, now=None) -> None:
        r = self.reminder(reminder_id)
        if not r or r["state"] != "pending":
            raise ValueError("Напоминание уже обработано или не найдено")
        if r["kind"] in ("location_load", "loading", "location_unload", "unloading"):
            raise ValueError("Для времени загрузки или выгрузки измени дату этапа целиком")
        eta = iso_minute(new_due_at)
        with self.con:
            self.con.execute("UPDATE reminders SET due_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (eta, reminder_id))
            self._event(r["route_id"], r["carrier_id"], "Время напоминания изменено",
                        f"{reminder_title(r['kind'])}: {eta}", now=now)

    def reminder_rows(self, *, until: str | None = None, due_only=False, now=None) -> list[dict]:
        sql = """SELECT m.*, r.origin, r.destination, r.weight, r.places,
            t.driver_name, t.driver_phone, c.carrier, c.phone AS carrier_phone
            FROM reminders m JOIN routes r ON r.id=m.route_id
            LEFT JOIN route_tracking t ON t.route_id=m.route_id AND t.cycle=m.cycle
            LEFT JOIN carriers c ON c.id=m.carrier_id
            WHERE m.state='pending'"""
        args = []
        if due_only:
            sql += " AND m.due_at<=?"
            args.append((now or datetime.now()).isoformat(timespec="minutes"))
        if until:
            sql += " AND m.due_at<=?"
            args.append(iso_minute(until))
        sql += " ORDER BY m.due_at ASC,m.id ASC"
        result = [dict(row) for row in self.con.execute(sql, args)]
        for row in result:
            row["title"] = reminder_title(row["kind"])
            row["route_label"] = route_label({**row, "id": row["route_id"]})
            row["contact_phone"] = row["driver_phone"] or row["carrier_phone"] or ""
            row["phone_is_driver"] = bool(row["driver_phone"])
        return result

    def today_tasks(self, *, now=None) -> list[dict]:
        today = (now or datetime.now()).strftime("%Y-%m-%d")
        return self.reminder_rows(until=f"{today}T23:59")

    def route_events(self, route_id: str, *, limit=30) -> list[dict]:
        return [dict(row) for row in self.con.execute(
            "SELECT * FROM route_events WHERE route_id=? ORDER BY id DESC LIMIT ?", (route_id, limit))]

    def export_csv(self, folder: Path | str) -> tuple[Path, Path]:
        """Export all fields in UTF-8 BOM CSV for Russian Excel; never change DB."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        result = []
        for name, fields, rows in (("routes", ROUTE_FIELDS + ROUTE_EXTRA_FIELDS,
                                   self.routes(include_archived=True)),
                                   ("carriers", CARRIER_FIELDS, self.carriers())):
            path = folder / f"logist_{name}.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            result.append(path)
        return tuple(result)

    def backup(self) -> Path:
        if self.vault is not None:
            return self.vault.backup_bytes(self.con.serialize())
        directory = self.path.parent / "backups"
        directory.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = directory / f"logist_{timestamp}.db"
        other = sqlite3.connect(dest)
        try:
            self.con.backup(other)
        finally:
            other.close()
        return dest
