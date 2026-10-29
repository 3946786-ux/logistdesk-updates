"""Pure call-card transformations; preserve historical fields during UI simplification."""
from __future__ import annotations

PAYMENT_TERMS = "По оригиналам, 10–15 б.д."
LEGACY_CALL_FIELDS = (
    "loading", "ready_date", "ready_time", "other_cargo", "hazardous_cargo",
)


def arrival_for_edit(record: dict) -> str:
    """Show the old separate date/time in one optional text field."""
    day = str(record.get("arrival_date") or "").strip()
    time = str(record.get("arrival_time") or "").strip()
    if time and time not in day:
        return f"{day} {time}".strip()
    return day


def call_answers(
    record: dict, *, body: str, arrival: str, etrn: str, provider: str,
    payment_confirmed: bool, payment: str, partial_load: str | None = None,
) -> dict:
    """Persist only the new answers; never erase old dogruz/ready data."""
    body = str(body or "").strip()
    arrival = str(arrival or "").strip()
    etrn = str(etrn or "").strip()
    if etrn not in ("", "Да", "Нет"):
        raise ValueError("ЭТрН: выбери Да, Нет или Не уточнил")
    if partial_load is None:
        partial_load = record.get("partial_load") or "Не уточнено"
    partial_load = str(partial_load).strip()
    if partial_load not in ("Да", "Нет", "", "Не уточнено"):
        raise ValueError("Догруз: выбери Да, Нет или Не уточнил")
    partial_load = partial_load if partial_load in ("Да", "Нет") else "Не уточнено"
    result = {key: record.get(key) for key in LEGACY_CALL_FIELDS}
    result.update({
        "body": body,
        "arrival_date": arrival,
        "arrival_time": "",  # Previously separate time is now included in arrival_date.
        "partial_load": partial_load,
        "etrn": etrn,
        "etrn_provider": (str(provider or "").strip() if etrn == "Да" else
                          "" if etrn == "Нет" else str(record.get("etrn_provider") or "").strip()),
        "payment": str(payment or "").strip() or (PAYMENT_TERMS if payment_confirmed else ""),
    "asked_body": int(bool(body) or bool(record.get("asked_body"))),
    "asked_schedule": int(bool(arrival) or bool(record.get("asked_schedule"))),
    "asked_partial": int(partial_load in ("Да", "Нет") or bool(record.get("asked_partial"))),
    "asked_etrn": int(etrn in ("Да", "Нет") or bool(record.get("asked_etrn"))),
        "payment_terms_communicated": int(bool(payment_confirmed)),
    })
    return result
