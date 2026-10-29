"""LogistDesk 2.1 offline-first, encrypted route/call/tracking/reminder change journal.

An operator-selected sync folder carries AES-GCM encrypted, immutable events.
Local IDs are never treated as global identifiers. Conflicts are recorded and
never silently overwritten. No PIN, partners, scans, or document files travel.
Nothing starts automatically; the UI must opt in for each program session.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from database import ROUTE_FIELDS, ROUTE_EXTRA_FIELDS, CARRIER_FIELDS
from portable_transfer import _key
from security import atomic_write

KINDS = ("route", "call", "tracking", "reminder", "event")
AAD = b"LogistDesk/ops-sync/v21"
MAX_EVENT_BYTES = 250_000
MAX_FILES = 10000
MAX_EVENTS_PER_TICK = 12
ROUTE_COLS = tuple(x for x in ROUTE_FIELDS if x != "id") + tuple(ROUTE_EXTRA_FIELDS)
CALL_COLS = tuple(x for x in CARRIER_FIELDS if x not in ("route_id", "source_key"))
TRACK_COLS = (
    "driver_name", "driver_phone", "phase", "cycle", "load_due_at",
    "unload_due_at", "photos_received", "signed_docs_received",
)
REMINDER_COLS = ("cycle", "kind", "due_at", "state")
EVENT_COLS = ("happened_at", "event", "details")


def _digest(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _seal(payload: dict, phrase: str) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("Запись синхронизации слишком большая")
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(_key(phrase, salt)).encrypt(nonce, raw, AAD)
    return json.dumps(
        {"format": "LD21-OPS", "salt": salt.hex(), "nonce": nonce.hex(),
         "encrypted": encrypted.hex()}, separators=(",", ":")).encode("ascii")


def _open(raw: bytes, phrase: str) -> dict:
    if len(raw) > MAX_EVENT_BYTES * 3:
        raise ValueError("Слишком большой пакет обмена")
    try:
        pkt = json.loads(raw)
        if pkt.get("format") != "LD21-OPS":
            raise ValueError("Неверный формат пакета")
        salt, nonce = bytes.fromhex(pkt["salt"]), bytes.fromhex(pkt["nonce"])
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError("Повреждённый пакет")
        clear = AESGCM(_key(phrase, salt)).decrypt(
            nonce, bytes.fromhex(pkt["encrypted"]), AAD)
        item = json.loads(clear)
        if (item.get("format") != 21 or item.get("kind") not in KINDS
                or not isinstance(item.get("value"), dict)
                or not isinstance(item.get("base"), str)
                or not isinstance(item.get("uid"), str)
                or not isinstance(item.get("digest"), str)
                or len(item["uid"]) != 32
                or len(item["digest"]) != 64
                or len(item["base"]) not in (0, 64)
                or _digest(item["value"]) != item["digest"]):
            raise ValueError("Повреждённая запись обмена")
        uuid.UUID(hex=item["uid"])
        return item
    except (InvalidTag, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Неверный пароль обмена или повреждённый пакет") from exc


class MissingDependency(Exception):
    pass


class OperationsSync21:
    """Keeps each device's native IDs while giving shared objects UUID identities."""

    def __init__(self, db, folder: str | Path, phrase: str):
        _key(phrase, b"\\0" * 16)
        self.db = db
        self.folder = Path(folder).resolve(strict=True)
        if not self.folder.is_dir():
            raise ValueError("Общая папка не найдена")
        self.phrase = phrase
        self.inbox = self.folder / "LogistDesk-Exchange-21" / "operations"
        self.inbox.mkdir(parents=True, exist_ok=True)
        existing = {x[0] for x in db.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "ops21_links" not in existing:
            db.backup()
        with db.con:
            db.con.executescript("""
                CREATE TABLE IF NOT EXISTS ops21_device(
                    id INTEGER PRIMARY KEY CHECK(id=1), uid TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ops21_links(
                    kind TEXT NOT NULL, local_key TEXT NOT NULL,
                    uid TEXT NOT NULL, origin_id TEXT NOT NULL DEFAULT '',
                    last_hash TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(kind,local_key), UNIQUE(kind,uid)
                );
                CREATE TABLE IF NOT EXISTS ops21_seen(
                    filename TEXT PRIMARY KEY, sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ops21_conflicts(
                    filename TEXT PRIMARY KEY, kind TEXT NOT NULL, uid TEXT NOT NULL,
                    details TEXT NOT NULL, detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ops21_tombstones(
                    uid TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    local_key TEXT NOT NULL, base_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS ops21_deleted_carrier
                BEFORE DELETE ON carriers
                BEGIN
                    INSERT OR REPLACE INTO ops21_tombstones(uid,kind,local_key,base_hash)
                    SELECT uid,kind,local_key,last_hash FROM ops21_links
                    WHERE kind='call' AND local_key=CAST(OLD.id AS TEXT);
                END;
            """)
            row = db.con.execute("SELECT uid FROM ops21_device WHERE id=1").fetchone()
            if row is None:
                db.con.execute(
                    "INSERT INTO ops21_device(id,uid) VALUES(1,?)", (uuid.uuid4().hex,))
        self.device = db.con.execute("SELECT uid FROM ops21_device WHERE id=1").fetchone()[0]

    def close(self):
        self.phrase = ""

    def _check(self):
        if not self.phrase or not self.folder.is_dir():
            raise ValueError("Защищённая синхронизация отключена или папка недоступна")

    def _link(self, kind: str, local_key: str):
        return self.db.con.execute(
            "SELECT * FROM ops21_links WHERE kind=? AND local_key=?", (kind, local_key)
        ).fetchone()

    def _by_uid(self, kind: str, uid: str):
        return self.db.con.execute(
            "SELECT * FROM ops21_links WHERE kind=? AND uid=?", (kind, uid)
        ).fetchone()

    def _uid(self, kind: str, key: str):
        row = self._link(kind, key)
        return row["uid"] if row else None

    def _required_uid(self, kind: str, local_key: str):
        uid = self._uid(kind, local_key)
        if not uid:
            raise MissingDependency(f"{kind}: {local_key}")
        return uid

    def _local_key(self, kind: str, uid: str):
        row = self._by_uid(kind, uid)
        if not row:
            raise MissingDependency(f"Нет связанной записи {kind}")
        return row["local_key"]

    def _rows(self, kind: str):
        table = {"route": "routes", "call": "carriers",
                 "tracking": "route_tracking", "reminder": "reminders",
                 "event": "route_events"}[kind]
        return [dict(r) for r in self.db.con.execute("SELECT * FROM " + table)]

    @staticmethod
    def _key_for(kind: str, r: dict):
        if kind == "route":
            return str(r["id"])
        if kind in ("call", "event"):
            return str(r["id"])
        if kind == "tracking":
            return str(r["route_id"])
        return str(r["route_id"]) + "|" + str(r["cycle"]) + "|" + str(r["kind"])

    def _value(self, kind: str, r: dict):
        if kind == "route":
            link = self._link(kind, str(r["id"]))
            return {"source_id": link["origin_id"] if link else str(r["id"]),
                    **{k: r[k] for k in ROUTE_COLS}}
        if kind == "call":
            return {"route_uid": self._required_uid("route", str(r["route_id"])),
                    **{k: r[k] for k in CALL_COLS}}
        if kind == "event":
            return {"route_uid": self._required_uid("route", str(r["route_id"])),
                    "call_uid": (self._required_uid("call", str(r["carrier_id"]))
                                 if r["carrier_id"] is not None else ""),
                    **{k: r[k] for k in EVENT_COLS}}
        if kind == "tracking":
            return {"route_uid": self._required_uid("route", str(r["route_id"])),
                    "call_uid": (self._required_uid("call", str(r["carrier_id"]))
                                 if r["carrier_id"] is not None else ""),
                    **{k: r[k] for k in TRACK_COLS}}
        return {"route_uid": self._required_uid("route", str(r["route_id"])),
                "call_uid": (self._required_uid("call", str(r["carrier_id"]))
                             if r["carrier_id"] is not None else ""),
                **{k: r[k] for k in REMINDER_COLS}}

    def _local_value(self, kind: str, key: str):
        if kind == "route":
            row = self.db.con.execute("SELECT * FROM routes WHERE id=?", (key,)).fetchone()
        elif kind == "call":
            row = self.db.con.execute("SELECT * FROM carriers WHERE id=?", (int(key),)).fetchone()
        elif kind == "event":
            row = self.db.con.execute("SELECT * FROM route_events WHERE id=?", (int(key),)).fetchone()
        elif kind == "tracking":
            row = self.db.con.execute("SELECT * FROM route_tracking WHERE route_id=?", (key,)).fetchone()
        else:
            route_id, cycle, reminder_kind = key.rsplit("|", 2)
            row = self.db.con.execute(
                "SELECT * FROM reminders WHERE route_id=? AND cycle=? AND kind=?",
                (route_id, int(cycle), reminder_kind)).fetchone()
        return self._value(kind, dict(row)) if row else None

    def _apply(self, kind: str, value: dict, link):
        """SQL writes only whitelisted columns; foreign IDs are translated."""
        con = self.db.con
        if kind == "route":
            source_id = str(value.get("source_id", "")).strip()
            if not source_id or len(source_id) > 40:
                raise ValueError("Некорректный номер рейса")
            local = link["local_key"] if link else (
                source_id if not self.db.get_route(source_id) else self.db.next_route_id())
            # preserve original route ID separately from local native ID.
            columns = ("id",) + ROUTE_COLS
            vals = [local] + [value[k] for k in ROUTE_COLS]
            self._upsert("routes", "id", columns, vals)
            return local, source_id
        if kind == "call":
            route_key = self._local_key("route", value["route_uid"])
            values = {k: value[k] for k in CALL_COLS}
            if link:
                local = link["local_key"]
                con.execute("UPDATE carriers SET " +
                            ",".join(f"{k}=?" for k in CALL_COLS) +
                            ",route_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            [values[k] for k in CALL_COLS] + [route_key, int(local)])
            else:
                cur = con.execute(
                    "INSERT INTO carriers(route_id," + ",".join(CALL_COLS) +
                    ") VALUES (" + ",".join("?" for _ in range(len(CALL_COLS) + 1)) + ")",
                    [route_key] + [values[k] for k in CALL_COLS])
                local = str(cur.lastrowid)
            return str(local), ""
        if kind == "event":
            route_key = self._local_key("route", value["route_uid"])
            call_id = int(self._local_key("call", value["call_uid"])) if value["call_uid"] else None
            if link:
                con.execute("UPDATE route_events SET route_id=?,carrier_id=?,"
                            "happened_at=?,event=?,details=? WHERE id=?",
                            [route_key, call_id] + [value[k] for k in EVENT_COLS]
                            + [int(link["local_key"])])
                return link["local_key"], ""
            cur = con.execute(
                "INSERT INTO route_events(route_id,carrier_id,happened_at,event,details)"
                " VALUES(?,?,?,?,?)",
                [route_key, call_id] + [value[k] for k in EVENT_COLS])
            return str(cur.lastrowid), ""
        if kind == "tracking":
            route_key = self._local_key("route", value["route_uid"])
            call_id = int(self._local_key("call", value["call_uid"])) if value["call_uid"] else None
            self._upsert("route_tracking", "route_id",
                         ("route_id", "carrier_id") + TRACK_COLS,
                         [route_key, call_id] + [value[k] for k in TRACK_COLS])
            return route_key, ""
        route_key = self._local_key("route", value["route_uid"])
        call_id = int(self._local_key("call", value["call_uid"])) if value["call_uid"] else None
        key = route_key + "|" + str(value["cycle"]) + "|" + str(value["kind"])
        con.execute("""
            INSERT INTO reminders(route_id,carrier_id,cycle,kind,due_at,state)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(route_id,cycle,kind) DO UPDATE SET
            carrier_id=excluded.carrier_id, due_at=excluded.due_at,
            state=excluded.state, updated_at=CURRENT_TIMESTAMP
            """, (route_key, call_id, value["cycle"], value["kind"],
                  value["due_at"], value["state"]))
        return key, ""

    def _upsert(self, table: str, primary: str, cols, vals):
        columns = ",".join(cols)
        marks = ",".join("?" for _ in cols)
        updates = ",".join(f"{k}=excluded.{k}" for k in cols if k != primary)
        self.db.con.execute(
            f"INSERT INTO {table}({columns}) VALUES({marks}) "
            f"ON CONFLICT({primary}) DO UPDATE SET {updates}",
            vals)

    def _accept(self, filename: str, sha: str, item: dict) -> str:
        # Apply the remote row and its UUID mapping in one database transaction.
        # A crash or malformed event must not leave an unmapped duplicate.
        with self.db.con:
            return self._accept_atomic(filename, sha, item)

    def _accept_atomic(self, filename: str, sha: str, item: dict) -> str:
        kind, uid, base, digest, value = (
            item["kind"], item["uid"], item["base"], item["digest"], item["value"])
        link = self._by_uid(kind, uid)
        if link:
            if digest == link["last_hash"]:
                outcome = "unchanged"
            else:
                current = self._local_value(kind, link["local_key"])
                if (link["last_hash"] != base or current is None
                        or _digest(current) != link["last_hash"]):
                    outcome = "conflict"
                else:
                    if kind == "call" and value.get("deleted") is True:
                        self.db.con.execute(
                            "DELETE FROM carriers WHERE id=?", (int(link["local_key"]),))
                        # Do not echo the received deletion as a new local event.
                        self.db.con.execute(
                            "DELETE FROM ops21_tombstones WHERE uid=?", (uid,))
                    else:
                        self._apply(kind, value, link)
                    outcome = "applied"
        elif base:
            raise MissingDependency("Исходная версия записи ещё не получена")
        else:
            # A new UID never overwrites an unrelated local route or call.
            new_key, origin_id = self._apply(kind, value, None)
            outcome = "created"
        if outcome == "applied":
            self.db.con.execute(
                "UPDATE ops21_links SET last_hash=? WHERE kind=? AND uid=?",
                (digest, kind, uid))
        elif outcome == "created":
            self.db.con.execute("""
                INSERT INTO ops21_links(kind,local_key,uid,origin_id,last_hash)
                VALUES(?,?,?,?,?)""", (kind, new_key, uid, origin_id, digest))
        if outcome == "conflict":
            self.db.con.execute(
                "INSERT OR IGNORE INTO ops21_conflicts(filename,kind,uid,details) VALUES(?,?,?,?)",
                (filename, kind, uid, "Разные изменения на двух компьютерах"))
        self.db.con.execute(
            "INSERT INTO ops21_seen(filename,sha256) VALUES(?,?)", (filename, sha))
        return outcome

    def _emit(self, kind: str, local_key: str, value: dict):
        link = self._link(kind, local_key)
        uid = link["uid"] if link else uuid.uuid4().hex
        base = link["last_hash"] if link else ""
        digest = _digest(value)
        if digest == base:
            return False
        msg = {"format": 21, "device": self.device, "uid": uid,
               "kind": kind, "base": base, "digest": digest, "value": value}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"LD21_op_{stamp}_{secrets.token_hex(8)}.ldx21"
        packet = _seal(msg, self.phrase)
        atomic_write(self.inbox / name, packet)
        with self.db.con:
            if link:
                self.db.con.execute(
                    "UPDATE ops21_links SET last_hash=? WHERE kind=? AND local_key=?",
                    (digest, kind, local_key))
            else:
                self.db.con.execute("""
                    INSERT INTO ops21_links(kind,local_key,uid,origin_id,last_hash)
                    VALUES(?,?,?,?,?)""",
                    (kind, local_key, uid,
                     value.get("source_id", "") if kind == "route" else "", digest))
            self.db.con.execute(
                "INSERT INTO ops21_seen(filename,sha256) VALUES(?,?)",
                (name, hashlib.sha256(packet).hexdigest()))
        return True

    def _emit_tombstones(self, limit: int):
        """Send actual hard deletions of linked calls; imported deletions never echo."""
        sent = 0
        rows = self.db.con.execute(
            "SELECT * FROM ops21_tombstones ORDER BY rowid LIMIT ?", (limit,)).fetchall()
        for row in rows:
            link = self._by_uid("call", row["uid"])
            if link is None:
                with self.db.con:
                    self.db.con.execute(
                        "DELETE FROM ops21_tombstones WHERE uid=?", (row["uid"],))
                continue
            value = {"deleted": True}
            base = row["base_hash"]
            digest = _digest(value)
            if link["last_hash"] == digest:
                with self.db.con:
                    self.db.con.execute(
                        "DELETE FROM ops21_tombstones WHERE uid=?", (row["uid"],))
                continue
            packet = _seal({
                "format": 21, "device": self.device, "uid": row["uid"],
                "kind": "call", "base": base, "digest": digest, "value": value
            }, self.phrase)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            name = f"LD21_op_{stamp}_{secrets.token_hex(8)}.ldx21"
            atomic_write(self.inbox / name, packet)
            with self.db.con:
                self.db.con.execute(
                    "UPDATE ops21_links SET last_hash=? WHERE kind='call' AND uid=?",
                    (digest, row["uid"]))
                self.db.con.execute(
                    "DELETE FROM ops21_tombstones WHERE uid=?", (row["uid"],))
                self.db.con.execute(
                    "INSERT INTO ops21_seen(filename,sha256) VALUES(?,?)",
                    (name, hashlib.sha256(packet).hexdigest()))
            sent += 1
        return sent

    def sync_once(self):
        self._check()
        files = sorted(self.inbox.glob("LD21_op_*.ldx21"))
        if len(files) > MAX_FILES:
            raise ValueError("Очередь синхронизации слишком большая")
        report = {"received": 0, "sent": 0, "conflicts": 0, "pending": 0}
        pending = []
        for path in files:
            if path.is_symlink() or not path.is_file():
                continue
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            seen = self.db.con.execute(
                "SELECT sha256 FROM ops21_seen WHERE filename=?", (path.name,)).fetchone()
            if seen:
                if sha != seen[0]:
                    raise ValueError("Ранее обработанный пакет изменён")
                continue
            item = _open(path.read_bytes(), self.phrase)
            if item.get("device") == self.device:
                with self.db.con:
                    self.db.con.execute(
                        "INSERT INTO ops21_seen(filename,sha256) VALUES(?,?)", (path.name, sha))
                continue
            pending.append((path.name, sha, item))
        # Imported events may depend on earlier route/call events. Do not discard
        # a dependent event simply because the cloud delivered it first.
        handled = 0
        for kind in KINDS:
            for name, sha, item in [x for x in pending if x[2]["kind"] == kind]:
                if handled >= MAX_EVENTS_PER_TICK:
                    report["pending"] += 1
                    continue
                try:
                    outcome = self._accept(name, sha, item)
                    report["conflicts" if outcome == "conflict" else "received"] += 1
                    handled += 1
                except MissingDependency:
                    report["pending"] += 1
        for kind in KINDS:
            for row in self._rows(kind):
                if report["sent"] >= MAX_EVENTS_PER_TICK:
                    break
                key = self._key_for(kind, row)
                try:
                    value = self._value(kind, row)
                except MissingDependency:
                    continue
                if self._emit(kind, key, value):
                    report["sent"] += 1
        if report["sent"] < MAX_EVENTS_PER_TICK:
            report["sent"] += self._emit_tombstones(MAX_EVENTS_PER_TICK - report["sent"])
        return report
