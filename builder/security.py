"""Local password-based encrypted SQLite storage for LogistDesk.

The database is deserialized into SQLite's in-memory connection; no decrypted
SQLite file is intentionally written to disk. Encrypted snapshots are saved
atomically after committed transactions. This does not protect an unlocked
process from an administrator or other malware running as the same user.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"LDENC1"
AAD_DB = b"LogistDesk.database.v1"
AAD_CHECK = b"LogistDesk.password-check.v1"
AAD_PIN_KEY = b"LogistDesk.quick-pin-key.v1"
CHECK_VALUE = b"LogistDesk vault unlocked"
KDF_MEMORY_KIB = 65536
KDF_ITERATIONS = 3
KDF_PARALLELISM = 2


class VaultError(Exception):
    """Safe error message for the user; never contains a password."""




def _protect_machine(data: bytes) -> bytes:
    """Protect bytes with the current Windows account (DPAPI)."""
    if os.name != "nt":
        if os.environ.get("LOGIST_PIN_TEST_MODE") == "1":
            return b"TESTDPAPI" + data
        raise VaultError("Быстрый PIN доступен только в Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "LogistDesk", None, None, None, 0, ctypes.byref(target)):
        raise VaultError("Windows не смог защитить ключ быстрого входа")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _unprotect_machine(data: bytes) -> bytes:
    """Reverse _protect_machine for the current Windows account."""
    if os.name != "nt":
        if os.environ.get("LOGIST_PIN_TEST_MODE") == "1" and data.startswith(b"TESTDPAPI"):
            return data[len(b"TESTDPAPI"):]
        raise VaultError("Этот PIN привязан к учётной записи Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise VaultError("PIN не удалось открыть в этой учётной записи Windows")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _validate_pin(pin: str, confirm: str | None = None) -> str:
    pin = (pin or "").strip()
    if not re.fullmatch(r"\d{4}", pin):
        raise VaultError("PIN должен состоять ровно из 4 цифр")
    if confirm is not None and pin != (confirm or "").strip():
        raise VaultError("PIN-коды не совпадают")
    return pin

def atomic_write(path: Path, data: bytes) -> None:
    """Write+fsync temporary file in the same directory, then atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".ld_", suffix=".tmp", dir=path.parent)
    tmp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _derive(password: str, salt: bytes) -> bytes:
    return hash_secret_raw(password.encode("utf-8"), salt, time_cost=KDF_ITERATIONS,
                           memory_cost=KDF_MEMORY_KIB, parallelism=KDF_PARALLELISM,
                           hash_len=32, type=Type.ID)


def _seal(key: bytes, data: bytes, aad: bytes = AAD_DB) -> bytes:
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, aad)


def _open(key: bytes, data: bytes, aad: bytes = AAD_DB) -> bytes:
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 12 + 16:
        raise VaultError("Файл не является защищённой базой LogistDesk или повреждён")
    start = len(MAGIC)
    try:
        return AESGCM(key).decrypt(data[start:start + 12], data[start + 12:], aad)
    except InvalidTag as exc:
        raise VaultError("Не удалось проверить целостность зашифрованных данных") from exc


def _validate_sqlite(raw: bytes) -> None:
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(raw)
        result = con.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise VaultError("Проверка целостности базы не пройдена")
    except sqlite3.DatabaseError as exc:
        raise VaultError("База SQLite повреждена или имеет неподдерживаемый формат") from exc
    finally:
        con.close()


class SecurityVault:
    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.meta_path = self.data_dir / "security.json"
        self.pin_path = self.data_dir / "quick_pin.json"
        self.encrypted_path = self.data_dir / "logist.db.enc"
        self.legacy_path = self.data_dir / "logist.db"
        self._key: bytes | None = None
        self.username = ""
        self._lock_handle = None

    def acquire_lock(self) -> None:
        """Prevent two instances from overwriting one another's encrypted snapshot."""
        if self._lock_handle is not None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.data_dir / "session.lock", "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise VaultError("LogistDesk уже запущен. Открой его через значок возле часов") from exc
        self._lock_handle = handle

    def release_lock(self) -> None:
        handle = self._lock_handle
        if handle is None:
            return
        self._lock_handle = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    @property
    def configured(self) -> bool:
        return self.meta_path.is_file()

    @property
    def pin_configured(self) -> bool:
        return self.pin_path.is_file()

    @property
    def legacy_password_available(self) -> bool:
        if not self.configured:
            return False
        try:
            return not bool(self._metadata().get("pin_only"))
        except VaultError:
            return False

    def _metadata(self) -> dict:
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if data["format"] != 1 or not data["username"]:
                raise ValueError("invalid format")
            return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise VaultError("Файл настроек защиты повреждён; не создавай новую учётную запись поверх данных") from exc

    def setup_pin(self, username: str, pin: str, confirm: str) -> None:
        """Create a new vault protected by a four-digit Windows-bound quick PIN."""
        username = username.strip()
        if not username or len(username) > 64:
            raise VaultError("Укажи логин длиной до 64 символов")
        pin = _validate_pin(pin, confirm)
        if self.configured or self.encrypted_path.exists():
            raise VaultError("Учётная запись или защищённая база уже существуют")
        master = secrets.token_bytes(32)
        salt = secrets.token_bytes(16)
        meta = {"format": 1, "username": username, "salt": salt.hex(),
                "check": _seal(master, CHECK_VALUE, AAD_CHECK).hex(),
                "pin_only": True,
                "created_at": datetime.now().isoformat(timespec="seconds")}
        atomic_write(self.meta_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
        self._key = master
        self.username = username
        try:
            self.enable_pin(pin, pin)
            self.ensure_database(allow_create=True)
        except Exception:
            self.pin_path.unlink(missing_ok=True)
            self.meta_path.unlink(missing_ok=True)
            self._key = None
            self.username = ""
            raise

    def enable_pin(self, pin: str, confirm: str) -> None:
        """Enable/replace a four-digit PIN without changing the database encryption key."""
        key = self._require_key()
        pin = _validate_pin(pin, confirm)
        salt = secrets.token_bytes(16)
        pin_key = _derive(pin, salt)
        wrapped = _protect_machine(_seal(pin_key, key, AAD_PIN_KEY))
        data = {"format": 1, "salt": salt.hex(), "wrapped_key": wrapped.hex(),
                "created_at": datetime.now().isoformat(timespec="seconds")}
        atomic_write(self.pin_path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def unlock_pin(self, pin: str, *, recovery: bool = False) -> None:
        pin = _validate_pin(pin)
        if not self.pin_configured:
            raise VaultError("Быстрый PIN ещё не настроен")
        try:
            data = json.loads(self.pin_path.read_text(encoding="utf-8"))
            if data.get("format") != 1:
                raise ValueError("unsupported pin format")
            pin_key = _derive(pin, bytes.fromhex(data["salt"]))
            wrapped = _unprotect_machine(bytes.fromhex(data["wrapped_key"]))
            key = _open(pin_key, wrapped, AAD_PIN_KEY)
            meta = self._metadata()
            check = _open(key, bytes.fromhex(meta["check"]), AAD_CHECK)
            if not hmac.compare_digest(check, CHECK_VALUE):
                raise VaultError("Неверный PIN")
        except (OSError, ValueError, KeyError, TypeError, VaultError) as exc:
            if isinstance(exc, VaultError) and str(exc) not in ("Неверный PIN",):
                # Hide cryptographic details for ordinary PIN mistakes.
                raise VaultError("Неверный PIN или PIN привязан к другой учётной записи Windows") from exc
            raise VaultError("Неверный PIN") from exc
        self._key = key
        self.username = meta["username"]
        if not recovery:
            self.ensure_database(allow_create=False)
            self.load_bytes()

    def verify_pin(self, pin: str) -> bool:
        old_key, old_user = self._key, self.username
        try:
            self.unlock_pin(pin, recovery=True)
            if old_key is not None and not hmac.compare_digest(old_key, self._key):
                return False
            return True
        except VaultError:
            return False
        finally:
            if old_key is not None:
                self._key, self.username = old_key, old_user

    def setup(self, username: str, password: str, confirm: str) -> None:
        username = username.strip()
        if not username or len(username) > 64:
            raise VaultError("Укажи логин длиной до 64 символов")
        if len(password) < 12 or len(password) > 256:
            raise VaultError("Пароль должен содержать от 12 до 256 символов")
        if password != confirm:
            raise VaultError("Пароли не совпадают")
        if self.configured or self.encrypted_path.exists():
            raise VaultError("Учётная запись или защищённая база уже существуют")
        salt = secrets.token_bytes(16)
        key = _derive(password, salt)
        meta = {"format": 1, "username": username, "salt": salt.hex(),
                "check": _seal(key, CHECK_VALUE, AAD_CHECK).hex(),
                "created_at": datetime.now().isoformat(timespec="seconds")}
        # Metadata is committed first. If interrupted, login can resume migration
        # from the untouched legacy database. Never overwrite existing data.
        atomic_write(self.meta_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
        self._key = key
        self.username = username
        self.ensure_database(allow_create=True)

    def unlock(self, username: str, password: str, *, recovery: bool = False) -> None:
        meta = self._metadata()
        if meta.get("pin_only"):
            raise VaultError("Используй 4-значный PIN")
        if not hmac.compare_digest(username.strip().encode(), meta["username"].encode()):
            raise VaultError("Неверный логин или пароль")
        try:
            key = _derive(password, bytes.fromhex(meta["salt"]))
            check = _open(key, bytes.fromhex(meta["check"]), AAD_CHECK)
            if not hmac.compare_digest(check, CHECK_VALUE):
                raise VaultError("Неверный логин или пароль")
        except (ValueError, VaultError) as exc:
            raise VaultError("Неверный логин или пароль") from exc
        self._key = key
        self.username = meta["username"]
        if not recovery:
            self.ensure_database(allow_create=False)
            self.load_bytes()  # Fail before opening the UI if ciphertext was altered.

    def verify_password(self, password: str) -> bool:
        if self._key is None:
            return False
        try:
            meta = self._metadata()
            key = _derive(password, bytes.fromhex(meta["salt"]))
            check = _open(key, bytes.fromhex(meta["check"]), AAD_CHECK)
            return hmac.compare_digest(check, CHECK_VALUE) and hmac.compare_digest(key, self._key)
        except (VaultError, ValueError):
            return False

    def _require_key(self) -> bytes:
        if self._key is None:
            raise VaultError("Сначала войди в LogistDesk")
        return self._key

    def load_bytes(self) -> bytes:
        key = self._require_key()
        if not self.encrypted_path.is_file():
            raise VaultError("Защищённая база не найдена. Проверь резервные копии")
        raw = _open(key, self.encrypted_path.read_bytes())
        _validate_sqlite(raw)
        return raw

    def save_bytes(self, raw: bytes) -> None:
        key = self._require_key()
        _validate_sqlite(raw)
        atomic_write(self.encrypted_path, _seal(key, raw))

    def backup_bytes(self, raw: bytes, *, prefix: str = "logist") -> Path:
        key = self._require_key()
        _validate_sqlite(raw)
        directory = self.data_dir / "backups"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = directory / f"{prefix}_{stamp}.ldbak"
        atomic_write(dest, _seal(key, raw))
        # Keep the non-secret KDF salt/metadata alongside encrypted backups.
        atomic_write(directory / "security_meta.json", self.meta_path.read_bytes())
        if self.pin_path.is_file():
            atomic_write(directory / "quick_pin.json", self.pin_path.read_bytes())
        # Verify the backup before reporting success.
        if _open(key, dest.read_bytes()) != raw:
            raise VaultError("Не удалось проверить зашифрованную резервную копию")
        return dest

    def restore_from_backup(self, backup: Path | str) -> None:
        """Verify backup first; preserve current encrypted bytes before replacement."""
        key = self._require_key()
        backup = Path(backup)
        if not backup.is_file():
            raise VaultError("Файл резервной копии не найден")
        ciphertext = backup.read_bytes()
        raw = _open(key, ciphertext)
        _validate_sqlite(raw)
        if self.encrypted_path.exists():
            directory = self.data_dir / "backups"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            atomic_write(directory / f"before_restore_{stamp}.enc", self.encrypted_path.read_bytes())
        atomic_write(self.encrypted_path, ciphertext)
        if self.load_bytes() != raw:
            raise VaultError("Восстановленная база не прошла проверку")

    def _legacy_bytes(self, source: Path) -> bytes:
        if not source.is_file():
            raise VaultError("Исходная база не найдена")
        source_con = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(":memory:")
        try:
            source_con.backup(target)
            raw = target.serialize()
            _validate_sqlite(raw)
            return raw
        except sqlite3.DatabaseError as exc:
            raise VaultError("Старая база повреждена; оригинал оставлен без изменений") from exc
        finally:
            source_con.close()
            target.close()

    def ensure_database(self, *, allow_create: bool = False) -> None:
        self._require_key()
        if not self.encrypted_path.is_file():
            if self.legacy_path.is_file():
                raw = self._legacy_bytes(self.legacy_path)
                # Recovery copy must exist BEFORE the plaintext is removed.
                self.backup_bytes(raw, prefix="before_protection")
            else:
                if not allow_create:
                    raise VaultError("Защищённая база отсутствует. Нельзя создавать пустую поверх утраченной; восстанови копию")
                con = sqlite3.connect(":memory:")
                try:
                    raw = con.serialize()
                finally:
                    con.close()
            self.save_bytes(raw)
            if self.legacy_path.is_file():
                # Check encrypted data before removing the plaintext database.
                if self.load_bytes() != raw:
                    raise VaultError("Миграция не прошла проверку; старая база не удалена")
                self._remove_legacy(self.legacy_path)
        elif self.legacy_path.exists():
            # A previous interrupted migration, or a newer legacy application.
            # Never silently discard potentially newer plaintext changes.
            raise VaultError("Найдены одновременно старая и зашифрованная базы. Сохрани обе и обратись к восстановлению")
        self._encrypt_old_backups()

    @staticmethod
    def _remove_legacy(path: Path) -> None:
        for old in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"),
                    Path(str(path) + "-journal")):
            if old.exists():
                try:
                    old.unlink()
                except OSError as exc:
                    raise VaultError("Зашифрованная копия готова, но старую базу не удалось удалить. Закрой другие экземпляры") from exc

    def _encrypt_old_backups(self) -> None:
        backup_dir = self.data_dir / "backups"
        if not backup_dir.exists():
            return
        for old in sorted(backup_dir.glob("*.db")):
            raw = self._legacy_bytes(old)
            self.backup_bytes(raw, prefix="legacy_backup")
            try:
                old.unlink()
            except OSError as exc:
                raise VaultError("Старая незашифрованная резервная копия осталась на диске") from exc


class EncryptedConnection:
    """sqlite3.Connection-compatible subset with atomic encrypted persistence."""
    def __init__(self, vault: SecurityVault):
        self.vault = vault
        self._con = sqlite3.connect(":memory:")
        self._con.deserialize(vault.load_bytes())
        self._con.execute("PRAGMA temp_store=MEMORY")

    @property
    def row_factory(self):
        return self._con.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._con.row_factory = value

    def execute(self, *args, **kwargs):
        return self._con.execute(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        result = self._con.executescript(*args, **kwargs)
        self._persist()
        return result

    def commit(self):
        self._con.commit()
        self._persist()

    def rollback(self):
        self._con.rollback()

    def serialize(self):
        return self._con.serialize()

    def backup(self, other):
        return self._con.backup(other)

    def _persist(self):
        self.vault.save_bytes(self._con.serialize())

    def __enter__(self):
        self._con.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        result = self._con.__exit__(exc_type, exc, tb)
        if exc_type is None:
            self._persist()
        return result

    def close(self):
        if self._con.in_transaction:
            self.commit()
        else:
            self._persist()
        self._con.close()
