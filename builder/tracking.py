"""Pure helpers for local, staged transport reminders (no network dependency)."""
from __future__ import annotations
from datetime import datetime, timedelta

REMINDER_TITLES = {
    "location_load": "Позвонить: где водитель перед загрузкой?",
    "loading": "Уточнить: прибыл и загрузился ли водитель?",
    "photos": "Попросить фотографии сопроводительных документов",
    "unload_eta": "Уточнить ожидаемые дату и время выгрузки",
    "location_unload": "Позвонить: где водитель перед выгрузкой?",
    "unloading": "Уточнить: выгрузился ли водитель?",
    "signed_docs": "Получить подписанные документы после выгрузки",
}
PHASES = ("К загрузке", "В пути", "Выгружен", "Завершён", "Пауза")


def parse_local_datetime(value: str | datetime) -> datetime:
    """Store minute-precision local wall time; never silently guess a timezone."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise ValueError("Укажи местное время без часового пояса")
        return value.replace(second=0, microsecond=0)
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    raise ValueError("Укажи дату и время в формате 30.09.2026 10:00")


def iso_minute(value: str | datetime) -> str:
    return parse_local_datetime(value).isoformat(timespec="minutes")


def before_arrival(eta: str | datetime, *, now: datetime | None = None, minutes: int = 60) -> str:
    """Never schedule a preliminary check earlier than the workflow was started."""
    instant = parse_local_datetime(eta) - timedelta(minutes=minutes)
    current = (now or datetime.now()).replace(second=0, microsecond=0)
    return max(instant, current).isoformat(timespec="minutes")


def display_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return parse_local_datetime(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(value)


def reminder_title(kind: str) -> str:
    return REMINDER_TITLES.get(kind, kind)
