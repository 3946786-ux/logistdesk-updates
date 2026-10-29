"""Завершение перевозки после фактической выгрузки.

Отдельно от статуса «Закрыт», который лишь подтверждает согласованную машину.
Ожидание подписанных документов не блокирует архивирование.
"""
from __future__ import annotations
from datetime import datetime


def finish_after_unloading(db, route_id: str, *, now=None) -> None:
    route = db.get_route(route_id)
    if route is None:
        raise ValueError("Рейс не найден")
    if route["deleted_at"]:
        raise ValueError("Нельзя завершить рейс из корзины")
    if route["archived"]:
        return
    if route["status"] != "Закрыт":
        raise ValueError("Сначала согласуй перевозчика и закрой рейс")
    tracking = db.tracking(route_id)
    if tracking is None or tracking["phase"] in ("К загрузке", "Пауза"):
        raise ValueError("Сначала подтверди загрузку и фактическую выгрузку рейса")
    timestamp = now or datetime.now()
    if tracking and tracking["phase"] == "В пути":
        # Кнопка «Завершить» подтверждает фактическую выгрузку.
        db.confirm_unloaded(route_id, now=timestamp)
        tracking = db.tracking(route_id)
    if tracking and tracking["phase"] == "Выгружен":
        with db.con:
            db.con.execute(
                "UPDATE route_tracking SET phase='Завершён',updated_at=CURRENT_TIMESTAMP WHERE route_id=?",
                (route_id,))
            # Pending signed_docs reminders remain active: documentation is
            # monitored independently of whether the trip is archived.
            db._event(route_id, tracking["carrier_id"],
                      "Перевозка завершена после выгрузки", now=timestamp)
    elif tracking and tracking["phase"] != "Завершён":
        raise ValueError("Сначала отметь фактическую выгрузку")
    db.archive_route(route_id, now=timestamp)
