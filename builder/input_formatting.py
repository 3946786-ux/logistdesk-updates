"""Convenient Russian entry helpers; old persisted values remain compatible."""
from __future__ import annotations
import re


def ru_phone(value: str) -> str:
    raw = str(value or "").strip()
    number = re.sub(r"\D", "", raw)
    if len(number) == 11 and number[0] in "78":
        number = number[1:]
    elif len(number) == 10 and number.startswith("9"):
        pass
    else:
        return raw
    return f"+7({number[:3]}) {number[3:6]}-{number[6:8]}-{number[8:]}"


def short_date(value: str) -> str:
    raw = str(value or "").strip()
    if re.search(r"[A-Za-zА-Яа-яЁё]", raw):
        return raw
    digits = re.sub(r"\D", "", raw)
    if not digits or len(digits) > 6:
        return raw
    if len(digits) <= 2:
        return digits
    if len(digits) <= 4:
        return digits[:2] + "." + digits[2:]
    return digits[:2] + "." + digits[2:4] + "." + digits[4:]


def series_number(value: str) -> str:
    raw = str(value or "")
    number = re.sub(r"\D", "", raw)
    if not number or len(number) > 10:
        return raw.strip()
    return number[:4] + (" " + number[4:] if len(number) > 4 else "")


def bind_formatter(edit, formatter) -> None:
    def apply(_):
        formatted = formatter(edit.text())
        if formatted != edit.text():
            edit.setText(formatted)
            edit.setCursorPosition(len(formatted))
    edit.textEdited.connect(apply)


def bind_phone(edit) -> None:
    bind_formatter(edit, ru_phone)


def bind_date(edit) -> None:
    bind_formatter(edit, short_date)


def bind_document(edit) -> None:
    bind_formatter(edit, series_number)
