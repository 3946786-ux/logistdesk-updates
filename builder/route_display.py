"""Non-destructive presentation helpers for the trips workspace.

The user's original SQLite values are never modified by these helpers.
"""
from __future__ import annotations

import re

_WEIGHT = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:т|тонн(?:а|ы)?|кг|kg|t)\s*$", re.IGNORECASE)
_VOLUME = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:м\s*[³3]|куб(?:\.?\s*м(?:етр(?:а|ов)?)?)?|m\s*[³3])\s*$", re.IGNORECASE)


def trip_display_fields(route: dict) -> dict[str, str]:
    """Return legible fields and a warning for an obvious weight/volume mix-up.

    Only when *both* fields carry unambiguous, opposite physical units do we
    display the weight from the cargo field. The record itself is untouched.
    """
    cargo = str(route.get('cargo') or '').strip()
    weight = str(route.get('weight') or '').strip()
    warning = ''
    if _WEIGHT.fullmatch(cargo) and _VOLUME.fullmatch(weight):
        warning = (
            f'Проверь поля рейса: в «Груз» записано «{cargo}» (вес), '
            f'а в «Вес» — «{weight}» (объём). Данные не изменены. '
            'Исправь их через «Редактировать рейс».'
        )
        return {'cargo': 'Не указан', 'weight': cargo, 'volume': weight, 'warning': warning}
    return {'cargo': cargo or '—', 'weight': weight or '—', 'volume': '', 'warning': warning}


def route_status_parts(route: dict, *, deleted_only: bool = False) -> list[tuple[str, str]]:
    """Status chips: document waiting is independent of the route's status."""
    if deleted_only or route.get('deleted_at'):
        return [('В корзине', 'muted')]
    status = str(route.get('status') or 'Выложен')
    kind = 'success' if status == 'Выложен' else 'danger' if status == 'Закрыт' else 'muted'
    parts = [(status, kind)]
    if route.get('carrier_docs_pending'):
        parts.append(('Жду документы', 'warning'))
    if route.get('archived'):
        parts.append(('Архив', 'muted'))
    return parts
