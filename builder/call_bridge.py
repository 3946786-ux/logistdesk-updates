"""Безопасное пополнение справочника из журнала телефонных предложений.

Не меняет существующие звонки. Не создаёт компании из пустых названий.
"""
from __future__ import annotations

from partner_registry import PartnerRegistry, digits


def ensure_call_links(registry: PartnerRegistry) -> None:
    registry.con.executescript("""
    CREATE TABLE IF NOT EXISTS partner_calls (
        carrier_call_id INTEGER PRIMARY KEY REFERENCES carriers(id) ON DELETE CASCADE,
        partner_id INTEGER NOT NULL REFERENCES partners(id)
    );
    CREATE INDEX IF NOT EXISTS idx_partner_calls_partner ON partner_calls(partner_id);
    """)


def register_call(registry: PartnerRegistry, call: dict, call_id: int) -> int | None:
    ensure_call_links(registry)
    name = str(call.get("carrier") or "").strip()
    phone = str(call.get("phone") or "").strip()
    if not name:
        return None
    existing = registry.con.execute(
        "SELECT partner_id FROM partner_calls WHERE carrier_call_id=?", (call_id,)).fetchone()
    if existing:
        return int(existing[0])
    candidates = [p for p in registry.search(name)
                  if p["name"].casefold() == name.casefold()
                  and (not p["phone"] or not phone
                       or digits(p["phone"]) == digits(phone))]
    if len(candidates) == 1:
        p = candidates[0]
        new = dict(p)
        if not p["phone"] and phone:
            new["phone"] = phone
        if p["role"] == "customer":
            new["role"] = "both"
        partner_id = registry.save_partner(new, p["id"])
    else:
        partner_id = registry.save_partner({
            "name": name, "role": "carrier", "phone": phone,
        })
    route_id = call.get("route_id") or ""
    with registry.con:
        registry.con.execute(
            "INSERT OR IGNORE INTO partner_calls(carrier_call_id,partner_id) VALUES(?,?)",
            (call_id, partner_id))
    if route_id and registry.db.get_route(str(route_id)):
        registry.link_route(partner_id, str(route_id), "carrier")
    driver_name = str(call.get("driver_name") or "").strip()
    driver_phone = str(call.get("driver_phone") or "").strip()
    if driver_name:
        parts = driver_name.split()
        if not any(
            " ".join((d["surname"], d["first_name"], d["patronymic"])).strip().casefold()
            == driver_name.casefold()
            and (not driver_phone or not d["phone"] or digits(d["phone"]) == digits(driver_phone))
            for d in registry.drivers(partner_id)
        ):
            registry.save_driver({
                "partner_id": partner_id, "surname": parts[0],
                "first_name": parts[1] if len(parts) > 1 else "",
                "patronymic": " ".join(parts[2:]),
                "phone": driver_phone,
            })
    return partner_id


def import_legacy_calls(registry: PartnerRegistry) -> dict[str, int]:
    """Одноразовый/повторный импорт; каждый звонок связывается лишь однажды."""
    ensure_call_links(registry)
    rows = [dict(r) for r in registry.con.execute(
        "SELECT id,route_id,carrier,phone,driver_name,driver_phone FROM carriers")]
    linked = 0
    skipped = 0
    for call in rows:
        partner_id = register_call(registry, call, call["id"])
        if partner_id:
            linked += 1
        else:
            skipped += 1
    return {"linked": linked, "skipped": skipped, "total": len(rows)}
