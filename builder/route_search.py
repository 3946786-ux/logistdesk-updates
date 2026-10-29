"""Token-based route search for the quick-call workflow (no Qt dependency)."""
from __future__ import annotations

import re
from rules import route_label


def normalize_search(value: object) -> str:
    """Ignore case, punctuation, arrows and the ё/е difference."""
    return " ".join(re.findall(r"[a-zа-я0-9]+", str(value or "").casefold().replace("ё", "е")))


def route_search_text(route: dict) -> str:
    return normalize_search(" ".join(str(route.get(field) or "") for field in (
        "id", "origin", "destination", "sender", "cargo", "weight", "places", "package_type",
    )))


def matching_routes(routes: list[dict], query: str, *, limit: int = 8) -> list[dict]:
    """Every word may occur in a different field, in any order.

    Example: 'набережные челны москва' matches 'Набережные Челны → Москва'.
    Distinct records are never merged: weight, places and ID remain visible.
    """
    tokens = normalize_search(query).split()
    if not tokens:
        return routes[:limit]
    return [route for route in routes if all(token in route_search_text(route) for token in tokens)][:limit]


def route_result_label(route: dict) -> str:
    first = route_label(route)
    extra = " · ".join(str(route.get(key) or "").strip() for key in ("sender", "cargo")
                       if str(route.get(key) or "").strip())
    return f"{first}\n{extra}" if extra else first
