"""Portable encrypted contact transfer between authorized LogistDesk installations.

This is NOT an automatic database replacement or a background cloud service:
it transfers *only* the contacts selected by the operator. Existing trips,
call history, credentials and PIN are never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from partner_registry import (
    PartnerRegistry, PARTNER_FIELDS, DRIVER_FIELDS, VEHICLE_FIELDS, digits
)

AAD = b"LogistDesk/contacts-transfer/v1"
MAX_FILE_BYTES = 12_000_000
PRIVATE_DRIVER_FIELDS = frozenset((
    "birth_date", "passport_series", "passport_number", "passport_issued",
    "passport_date", "passport_department", "license_number",
    "license_categories", "license_date", "license_expires",
))
PRIVATE_VEHICLE_FIELDS = frozenset(("registration_series", "registration_number", "owner"))


def _key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 12:
        raise ValueError("Нужна отдельная парольная фраза длиной от 12 символов (не PIN)")
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt,
                          n=2**14, r=8, p=1, dklen=32, maxmem=32*1024*1024)


def _dump(registry: PartnerRegistry, include_private: bool) -> dict:
    partners = [dict(x) for x in registry.con.execute("SELECT * FROM partners ORDER BY id")]
    if len(partners) > 50000:
        raise ValueError("Слишком много контактов для одной выгрузки")
    result = []
    for p in partners:
        driver_fields = [field for field in DRIVER_FIELDS if field != "partner_id"
                         and (include_private or field not in PRIVATE_DRIVER_FIELDS)]
        vehicle_fields = [field for field in VEHICLE_FIELDS if field != "partner_id"
                          and (include_private or field not in PRIVATE_VEHICLE_FIELDS)]
        result.append({
            "partner": {field: p.get(field) or "" for field in PARTNER_FIELDS},
            "drivers": [{field: d.get(field) or "" for field in driver_fields}
                        for d in registry.drivers(p["id"])],
            "vehicles": [{field: v.get(field) or "" for field in vehicle_fields}
                         for v in registry.vehicles(p["id"])],
        })
    return {"format": 1, "kind": "contacts", "private_included": include_private, "entries": result}


def export_contacts(registry: PartnerRegistry, destination: str | Path,
                    passphrase: str, *, include_private: bool = False) -> dict:
    bundle = _dump(registry, include_private)
    plaintext = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode()
    if len(plaintext) > MAX_FILE_BYTES:
        raise ValueError("База слишком большая для одного защищённого экспорта")
    salt, nonce = os.urandom(16), os.urandom(12)
    ciphertext = AESGCM(_key(passphrase, salt)).encrypt(nonce, plaintext, AAD)
    packet = json.dumps({
        "format": "LDX1", "salt": salt.hex(), "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex(),
    }, separators=(",", ":")).encode("ascii")
    path = Path(destination)
    if path.suffix.lower() != ".ldx":
        raise ValueError("Для защищённого экспорта используй расширение .ldx")
    if path.exists():
        raise ValueError("Файл уже существует. Укажи другое имя, чтобы не перезаписать копию.")
    path.parent.mkdir(parents=True, exist_ok=True)
    from security import atomic_write
    atomic_write(path, packet)
    return {"companies": len(bundle["entries"]), "private_included": include_private}


def _decrypt(path: str | Path, passphrase: str) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES*3:
        raise ValueError("Защищённый файл слишком большой")
    try:
        packet = json.loads(path.read_text(encoding="ascii"))
        if packet.get("format") != "LDX1":
            raise ValueError("Неизвестный формат файла")
        salt = bytes.fromhex(packet["salt"])
        nonce = bytes.fromhex(packet["nonce"])
        encrypted = bytes.fromhex(packet["ciphertext"])
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError("Повреждённый защищённый файл")
        raw = AESGCM(_key(passphrase, salt)).decrypt(nonce, encrypted, AAD)
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("kind") != "contacts" or result.get("format") != 1:
            raise ValueError("Неверная структура базы контактов")
        if not isinstance(result.get("entries"), list) or len(result["entries"]) > 50000:
            raise ValueError("Некорректный список компаний")
        return result
    except (InvalidTag, KeyError, UnicodeError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Неверный пароль или повреждённый защищённый файл") from exc


def import_contacts(registry: PartnerRegistry, path: str | Path,
                    passphrase: str) -> dict[str, int]:
    """Импорт без перезаписи чужих записей; конфликтные значения сохраняются."""
    data = _decrypt(path, passphrase)
    # Reject malformed files *before* creating any database records.
    for item in data["entries"]:
        if not isinstance(item, dict) or not isinstance(item.get("partner"), dict):
            raise ValueError("Повреждённая карточка организации")
        if not isinstance(item.get("drivers"), list) or not isinstance(item.get("vehicles"), list):
            raise ValueError("Повреждённый список водителей или автомобилей")
        if len(item["drivers"]) > 2000 or len(item["vehicles"]) > 2000:
            raise ValueError("Слишком много записей в одной компании")
    registry.db.backup()
    report = {"new_companies": 0, "existing_companies": 0,
              "drivers": 0, "vehicles": 0, "conflicts": 0}
    for item in data["entries"]:
        p = {k: str(item["partner"].get(k) or "")[:1500] for k in PARTNER_FIELDS}
        existing = registry.find_inn(p.get("inn", ""))
        if existing is None:
            name = p.get("name", "").casefold()
            matches = [x for x in registry.search(p["name"]) if x["name"].casefold() == name]
            if len(matches) == 1 and (not p["phone"] or not matches[0]["phone"]
                                      or digits(matches[0]["phone"]) == digits(p["phone"])):
                existing = matches[0]
        if existing:
            new = dict(existing)
            for key in PARTNER_FIELDS:
                if key == "role":
                    new[key] = ("both" if p[key] != existing[key]
                                and p[key] and existing[key] else existing[key] or p[key])
                elif p[key] and not existing[key]:
                    new[key] = p[key]
                elif p[key] and existing[key] and p[key] != existing[key]:
                    report["conflicts"] += 1
            partner_id = registry.save_partner(new, existing["id"])
            report["existing_companies"] += 1
        else:
            partner_id = registry.save_partner(p)
            report["new_companies"] += 1
        known_drivers = registry.drivers(partner_id)
        for src in item["drivers"]:
            if not isinstance(src, dict):
                continue
            driver = {k: str(src.get(k) or "")[:1500]
                      for k in DRIVER_FIELDS if k != "partner_id"}
            license_no = digits(driver.get("license_number"))
            if license_no and any(digits(d["license_number"]) == license_no for d in known_drivers):
                continue
            full_name = " ".join(driver.get(f, "") for f in ("surname", "first_name", "patronymic")).casefold().strip()
            if full_name and any(
                " ".join(d.get(f, "") for f in ("surname", "first_name", "patronymic")).casefold().strip() == full_name
                and (driver.get("phone") and digits(d["phone"]) == digits(driver["phone"]))
                for d in known_drivers):
                continue
            driver["partner_id"] = partner_id
            try:
                registry.save_driver(driver)
            except ValueError:
                report["conflicts"] += 1
                continue
            report["drivers"] += 1
            known_drivers.append(driver)
        known_vehicles = registry.vehicles(partner_id)
        for src in item["vehicles"]:
            if not isinstance(src, dict):
                continue
            vehicle = {k: str(src.get(k) or "")[:1500] for k in VEHICLE_FIELDS if k != "partner_id"}
            vin, plate = vehicle.get("vin", "").upper(), vehicle.get("plate", "").casefold()
            if vin and any(v["vin"].upper() == vin for v in known_vehicles):
                continue
            if plate and any(v["plate"].casefold() == plate for v in known_vehicles):
                continue
            vehicle["partner_id"] = partner_id
            try:
                registry.save_vehicle(vehicle)
            except ValueError:
                report["conflicts"] += 1
                continue
            report["vehicles"] += 1
            known_vehicles.append(vehicle)
    return report
