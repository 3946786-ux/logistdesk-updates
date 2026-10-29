"""Бизнес-правила: поля остаются редактируемыми пользователем."""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VAT_RATE = 0.22  # Настройка пользователя для расчётов внутри приложения.
ROUND_STEP = 1000

SENDERS = ["Втормет", "Татпроф", "Бикотекс", "Агрисовгаз", "Востхимволокно", "Метресурс", "Алюминиевый сад"]
PACKAGES = ["", "Европалеты", "Палеты", "Поддоны", "Коробки", "Ящики", "Биг-бэги", "Мешки", "Бочки", "Рулоны", "Связки", "Навалом", "Без упаковки"]
BODIES = ["", "Тент", "Изотерм", "Термос", "Рефрижератор", "Бортовой", "Открытая", "Цельнометаллический фургон", "Контейнеровоз", "Трал", "Другой"]
LOADING = ["", "Зад", "Верх", "Бок", "Верх/бок", "Зад/бок", "Зад/зад", "Бок/бок", "Любая"]
ROUTE_STATUSES = ["Выложен", "Закрыт", "Отменён"]
CARRIER_STATUSES = ["Черновик", "Новый", "Думает", "Перезвонить", "Согласован", "Отказ"]
VAT_OPTIONS = ["", "С НДС", "Без НДС"]
CUSTOMER_STATUSES = ["Не отправлено", "На согласовании", "Согласовано", "Отказ"]
CUSTOMER_VAT_OPTIONS = ["Как у перевозчика", "С НДС", "Без НДС"]
DEFAULT_MARKUP_PERCENT = "15"
DEFAULT_FIXED_FEE = 3000
DEFAULT_PERSONAL_PERCENT = "15"


def sender_dimensions(sender: str) -> str:
    """Known pallet dimensions that may be prefilled for a new route."""
    s = (sender or "").strip().casefold().replace("ё", "е")
    if s == "бикотекс":
        return "1.2 × 0.8 × 1.8 м"
    return ""


def sender_conditions(sender: str, cargo: str = "") -> str:
    """Подсказки для новых рейсов; не перезаписывают пользовательские условия."""
    s = (sender or "").strip().casefold().replace("ё", "е")
    c = (cargo or "").strip().casefold().replace("ё", "е")
    if s == "втормет":
        return "Верх/бок"
    if s == "татпроф":
        return "Задняя съёмная балка; грузоподъёмность по СТС; ремни; верх/бок"
    if s == "бикотекс":
        return "Салфетки; загрузка сзади"  # Габариты в другом поле.
    if s == "агрисовгаз":
        return "Алюминиевый профиль; задняя съёмная балка; верх/бок"
    if s == "алюминиевый сад":
        return "Задняя съёмная балка; грузоподъёмность по СТС; ремни; верх/бок; загрузка до 14:00"
    if s == "метресурс":
        return "Размер поддонов 1,1 × 1,4 м"
    if s == "востхимволокно":
        base = "Размеры фуры 13,6 × 2,45 × 2,6 м"
        if "флейк" in c:
            return "Усиленная обрешётка; бок/бок; " + base
        if "пряж" in c:
            return "Жёсткая обрешётка; фото обрешётки; загрузка сзади; " + base
        if "волокн" in c:
            return "Верх/бок; " + base
        return base + "; уточнить вид груза"
    return ""


def parse_money(value) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("₽", "").replace("р.", "")
    if re.fullmatch(r"-?\d{1,3}(?:[.]\d{3})+", text):
        text = text.replace(".", "")
    elif re.fullmatch(r"-?\d+[.,]0{1,2}", text):
        text = re.split(r"[.,]", text)[0]
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError(f"Сумма должна быть целым числом рублей: {value}")
    return int(text)


def net_rate(with_vat, enabled: bool, manual=None, *, vat: float = VAT_RATE, step: int = ROUND_STEP) -> int | None:
    if not enabled:
        return None
    own = parse_money(manual)
    if own is not None:
        return own
    gross = parse_money(with_vat)
    if gross is None:
        return None
    if step <= 0 or vat < 0:
        raise ValueError("Некорректные настройки НДС/округления")
    return int((gross / (1 + vat)) // step) * step


def money(value) -> str:
    try:
        result = parse_money(value)
    except ValueError:
        return str(value)
    return "" if result is None else f"{result:,}".replace(",", " ") + " ₽"


def parse_percent(value, *, default: str = "15", maximum: int = 100) -> Decimal:
    """Parse percentages without binary floating-point rounding."""
    raw = default if value is None or str(value).strip() == "" else str(value)
    raw = raw.strip().replace(" ", "").replace("%", "").replace(",", ".")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Некорректный процент: {value}") from exc
    if not result.is_finite() or not (0 <= result <= maximum):
        raise ValueError(f"Процент должен быть от 0 до {maximum}: {value}")
    return result


def money_precise(value: Decimal | int | None) -> str:
    """Show kopeks when a commission has a fractional-ruble remainder."""
    if value is None:
        return "—"
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == amount.to_integral_value():
        return money(int(amount))
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def quote_calculation(carrier: dict) -> dict:
    """Quote the CUSTOMER from the carrier's requested rate, never the ATI listing.

    An approved customer rate replaces the suggested quote only after the
    customer_status becomes 'Согласовано'. Until then all margins are previews.
    A difference between VAT modes makes a direct margin comparison invalid.
    Amounts are the user's arithmetic spread, NOT accounting profit after tax.
    """
    requested = parse_money(carrier.get("desired_rate"))
    markup = parse_percent(carrier.get("markup_percent"), default=DEFAULT_MARKUP_PERCENT, maximum=1000)
    personal = parse_percent(carrier.get("personal_percent"), default=DEFAULT_PERSONAL_PERCENT)
    fee = parse_money(carrier.get("fixed_fee"))
    fee = DEFAULT_FIXED_FEE if fee is None else fee
    agreed = parse_money(carrier.get("customer_agreed_rate"))
    if any(v is not None and v < 0 for v in (requested, fee, agreed)):
        raise ValueError("Ставки и фиксированная надбавка не могут быть отрицательными")

    status = carrier.get("customer_status") or "Не отправлено"
    confirmed = status == "Согласовано" and agreed is not None
    quote = None
    if requested is not None:
        quote = int((Decimal(requested) * (1 + markup / 100) + fee)
                    .quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    carrier_vat = (carrier.get("vat_type") or "").strip().casefold()
    customer_vat = (carrier.get("customer_vat_type") or "Как у перевозчика").strip().casefold()
    if customer_vat == "как у перевозчика":
        customer_vat = carrier_vat
    recognized_vat = {"с ндс", "без ндс"}
    mismatched_vat = (carrier_vat in recognized_vat and customer_vat in recognized_vat
                      and carrier_vat != customer_vat)
    vat_warning = ""
    if mismatched_vat:
        vat_warning = "Разный НДС у перевозчика и заказчика: прямую маржу считать нельзя."
    elif carrier_vat not in recognized_vat or customer_vat not in recognized_vat:
        vat_warning = "НДС не указан или не распознан: разница арифметическая, без налогового расчёта."

    basis = agreed if confirmed else (None if status in ("Отказ", "Согласовано") else quote)
    margin = None
    share = None
    if requested is not None and basis is not None and not mismatched_vat:
        margin = basis - requested
        if margin > 0:
            share = (Decimal(margin) * personal / 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        elif margin == 0:
            share = Decimal("0.00")

    return {
        "requested_rate": requested,
        "quote": quote,
        "agreed_rate": agreed,
        "basis_rate": basis,
        "markup_percent": markup,
        "fixed_fee": fee,
        "personal_percent": personal,
        "customer_status": status,
        "confirmed": confirmed,
        "company_margin": margin,
        "personal_share": share,  # None on a loss or incomparable VAT regimes.
        "vat_warning": vat_warning,
    }


def route_label(route: dict) -> str:
    route_id = route.get("id") or "Новый"
    origin = route.get("origin") or "?"
    dest = route.get("destination") or "?"
    parts = [str(route_id), f"{origin} → {dest}"]
    if route.get("weight"):
        parts.append(str(route["weight"]))
    places = route.get("places")
    if places not in (None, "", 0, "0"):
        package = (route.get("package_type") or "").casefold()
        unit = "пал." if any(x in package for x in ("палет", "поддон")) else "мест"
        parts.append(f"{places} {unit}")
    return " | ".join(parts)


def card_text(route: dict) -> str:
    lines = [f"{route.get('origin') or '—'} → {route.get('destination') or '—'}"]
    for label, field in [("Отправитель", "sender"), ("Груз", "cargo"), ("Габариты", "dimensions"),
                         ("Вес / объём", "weight"), ("Способ загрузки", "loading"), ("Загрузка", "date_window"),
                         ("Выгрузка", "unload_window")]:
        if route.get(field) not in (None, ""):
            lines.append(f"{label}: {route[field]}")
    if route.get("places") not in (None, ""):
        pkg = str(route.get("package_type") or "мест").strip()
        lines.append(f"Упаковка: {route['places']} {pkg}")
    elif route.get("package_type"):
        lines.append(f"Упаковка: {route['package_type']}")
    if route.get("with_vat") not in (None, ""):
        lines.append(f"Ставка на ATI с НДС: {money(route['with_vat'])}")
    net = net_rate(route.get("with_vat"), bool(route.get("has_without_vat")), route.get("manual_without_vat"))
    if net is not None:
        lines.append(f"Ставка на ATI без НДС: {money(net)}")
    conditions = "; ".join(x for x in [route.get("sender_conditions"), route.get("own_conditions")] if x and str(x).strip())
    if conditions:
        lines.append(f"Обязательные условия: {conditions}")
    if route.get("note"):
        lines.append(f"Примечание: {route['note']}")
    return "\n".join(lines)


def normalize_phone(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits[0] in "78":
        return "7" + digits[1:]
    return digits


def rate_difference(route: dict, carrier: dict) -> int | None:
    """Legacy ATI comparison, retained for compatibility; NOT customer margin.

    The 0.5 UI uses quote_calculation() exclusively for commercial calculations.
    """
    desired = parse_money(carrier.get("desired_rate"))
    vat = (carrier.get("vat_type") or "").strip().casefold()
    if desired is None:
        return None
    if vat == "с ндс":
        base = parse_money(route.get("with_vat"))
    elif vat == "без ндс":
        base = net_rate(route.get("with_vat"), bool(route.get("has_without_vat")),
                        route.get("manual_without_vat"))
    else:
        return None
    return desired - base if base is not None else None
