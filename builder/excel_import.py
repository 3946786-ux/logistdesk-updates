"""Чтение существующих XLSX средствами стандартной библиотеки.

Исходный Excel НЕ изменяется. Формулы из старого файла не исполняются:
берутся сохранённые значения и ввод пользователя. Это защищает от старых
ошибок #REF!/#NAME? после перестановки столбцов.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile
from database import Database
from rules import parse_money, sender_conditions

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col(cell_ref: str) -> str:
    return re.match(r"[A-Z]+", cell_ref)[0]


def _read_xlsx(path: str | Path) -> dict[str, dict[int, dict[str, object]]]:
    result: dict[str, dict[int, dict[str, object]]] = {}
    try:
        with ZipFile(path) as zip_file:
            strings = []
            if "xl/sharedStrings.xml" in zip_file.namelist():
                root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
                strings = ["".join(n.text or "" for n in si.iter(NS + "t")) for si in root.findall(NS + "si")]
            workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
            relations = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
            paths = {x.attrib["Id"]: x.attrib["Target"] for x in relations}
            for sheet in workbook.findall(NS + "sheets/" + NS + "sheet"):
                name = sheet.attrib["name"]
                if name not in ("Рейсы", "Машины"):
                    continue
                target = paths[sheet.attrib[REL + "id"]].lstrip("/")
                target = target if target.startswith("xl/") else posixpath.normpath(posixpath.join("xl", target))
                root = ET.fromstring(zip_file.read(target))
                rows = {}
                for row in root.findall(NS + "sheetData/" + NS + "row"):
                    rownum = int(row.attrib["r"])
                    if rownum < 5:
                        continue
                    cells = {}
                    for cell in row.findall(NS + "c"):
                        value = cell.find(NS + "v")
                        inline = cell.find(NS + "is")
                        if value is not None and value.text is not None:
                            raw = value.text
                            typ = cell.attrib.get("t", "")
                            if typ == "s":
                                v = strings[int(raw)]
                            elif typ in ("str", "e"):
                                v = raw
                            elif typ == "b":
                                v = bool(int(raw))
                            else:
                                v = float(raw) if "." in raw or "E" in raw.upper() else int(raw)
                        elif inline is not None:
                            v = "".join(t.text or "" for t in inline.iter(NS + "t"))
                        else:
                            continue
                        if v is not None and str(v).strip():
                            cells[_col(cell.attrib["r"])] = v
                    if cells:
                        rows[rownum] = cells
                result[name] = rows
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("Не удалось прочитать Excel. Нужен файл .xlsx с листами «Рейсы» и «Машины».") from exc
    if "Рейсы" not in result:
        raise ValueError("В файле не найден лист «Рейсы».")
    return result


def _header_map(rows: dict[int, dict[str, object]]) -> dict[str, str]:
    return {str(value).strip().casefold(): col for col, value in rows.get(5, {}).items()}


def _field(row, head, aliases, fallback=""):
    # После вставки столбцов нельзя брать запасной номер колонки, когда есть
    # настоящие заголовки: так «палеты» попадали в количество мест.
    def normalize(value):
        return " ".join(str(value).replace("\n", " ").casefold().split())

    normalized = [(normalize(title), col) for title, col in head.items()]
    for alias in aliases:
        match = next((col for title, col in normalized if title == normalize(alias)), None)
        if match:
            return row.get(match)
    for alias in aliases:
        match = next((col for title, col in normalized if title.startswith(normalize(alias))), None)
        if match:
            return row.get(match)
    return None if head else (row.get(fallback) if fallback else None)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _date(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) and 20000 < float(value) < 80000:
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).strftime("%d.%m.%Y")
    return _text(value)


def _safe_money(value):
    try:
        return parse_money(value)
    except ValueError:
        return None


def _route_rows(rows):
    head = _header_map(rows)
    for rownum in sorted(rows):
        if rownum <= 5:
            continue
        row = rows[rownum]
        route_id = _text(_field(row, head, ["ID рейса"], "A")).upper()
        origin = _text(_field(row, head, ["Загрузка"], "C"))
        dest = _text(_field(row, head, ["Выгрузка"], "D"))
        if not (re.fullmatch(r"R\d+", route_id) and origin and dest):
            continue  # Пронумерованная, но пока пустая строка — не рейс.
        sender = _text(_field(row, head, ["Отправитель"], "B"))
        cargo = _text(_field(row, head, ["Груз / описание", "Груз"], "E"))
        auto = _text(_field(row, head, ["Условия отправителя"], "K"))
        custom = _text(_field(row, head, ["Условия рейса"], "L"))
        final = _text(_field(row, head, ["Обязательные условия (итог)"], "M"))
        if not auto:
            auto = sender_conditions(sender, cargo)
            if not auto and not custom:
                custom = final
        own = _safe_money(_field(row, head, ["Без НДС: своя ставка"], "P"))
        vat_enabled = _text(_field(row, head, ["Есть ставка без НДС?"], "O")).casefold() == "да" or own is not None
        record = {
            "id": route_id,
            "sender": sender,
            "origin": origin,
            "destination": dest,
            "cargo": cargo,
            "dimensions": _text(_field(row, head, ["Габариты", "Размеры", "Габариты груза"], "F")),
            "package_type": _text(_field(row, head, ["Упаковка", "Тип упаковки", "Тара"], "G")),
            "places": _text(_field(row, head, ["Кол-во мест", "Количество мест", "Мест", "Кол. мест", "К-во мест"], "H")),
            "weight": _text(_field(row, head, ["Вес / объём", "Вес", "Вес/объем", "Объем", "Вес груза"], "I")),
            "loading": _text(_field(row, head, ["Способ загрузки"], "J")),
            "sender_conditions": auto,
            "own_conditions": custom,
            "with_vat": _safe_money(_field(row, head, ["Ставка для перевозчика с НДС"], "N")),
            "has_without_vat": int(vat_enabled),
            "manual_without_vat": own,
            "date_window": _text(_field(row, head, ["Загрузка", "Дата / окно"], "R")),
            "unload_window": _text(_field(row, head, ["Выгрузка"], None)),
            "status": _text(_field(row, head, ["Статус рейса"], "S")) or "Выложен",
            "note": _text(_field(row, head, ["Примечание"], "U")),
        }
        yield record


def _carrier_rows(rows):
    head = _header_map(rows)
    for rownum in sorted(rows):
        if rownum <= 5:
            continue
        row = rows[rownum]
        selected = _text(_field(row, head, ["ID выбранного рейса"], "AB"))
        if not re.fullmatch(r"R\d+", selected):
            label = _text(_field(row, head, ["Рейс: маршрут"], "B"))
            found = re.match(r"^(R\d+)\b", label, re.IGNORECASE)
            selected = found.group(1).upper() if found else ""
        if not selected:
            continue
        carrier = _text(_field(row, head, ["Перевозчик / ФИО"], "D"))
        phone = _text(_field(row, head, ["Телефон"], "E"))
        body = _text(_field(row, head, ["Тип машины"], "F"))
        desired = _safe_money(_field(row, head, ["Желаемая ставка перевозчика"], "M"))
        comment = _text(_field(row, head, ["Комментарий"], "Q"))
        call_date = _date(_field(row, head, ["Дата звонка"], "A"))
        has_details = bool(carrier or phone or body or desired is not None or comment or call_date)
        record = {
            "route_id": selected, "call_date": call_date, "carrier": carrier, "phone": phone, "body": body,
            "loading": _text(_field(row, head, ["Загрузка"], "G")),
            "ready_date": _date(_field(row, head, ["Готов (дата)"], "H")),
            "ready_time": _text(_field(row, head, ["Время"], "I")),
            "etrn": _text(_field(row, head, ["ЕТрН"], "J")),
            "etrn_provider": _text(_field(row, head, ["Оператор ЕТрН"], "K")),
            "vat_type": _text(_field(row, head, ["НДС"], "L")),
            "desired_rate": desired,
            "payment": _text(_field(row, head, ["Условия оплаты"], "N")),
            "status": _text(_field(row, head, ["Статус"], "O")) or ("Новый" if has_details else "Черновик"),
            "callback_date": _date(_field(row, head, ["Перезвонить (дата)"], "P")),
            "comment": comment,
        }
        # Стабильный ключ, независимый от имени файла и ручной смены имени.
        signature = f"{rownum}|{selected}|{phone}|{call_date}|{desired}|{comment}"
        record["source_key"] = "excel:" + sha256(signature.encode("utf-8")).hexdigest()
        yield record


def import_excel(db: Database, path: str | Path) -> dict[str, int]:
    data = _read_xlsx(path)
    routes = list(_route_rows(data["Рейсы"]))
    carriers = list(_carrier_rows(data.get("Машины", {})))
    report = {"routes_new": 0, "routes_skipped": 0, "carriers_new": 0, "carriers_skipped": 0}
    # Перед импортом сохраняем локальную базу, если там уже есть данные.
    if db.routes() or db.carriers():
        db.backup()
    for route in routes:
        if db.get_route(route["id"]):
            report["routes_skipped"] += 1
        else:
            db.save_route(route, replace=False)
            report["routes_new"] += 1
    for carrier in carriers:
        if not db.get_route(carrier["route_id"]):
            report["carriers_skipped"] += 1
            continue
        previous = db.con.total_changes
        db.save_carrier(carrier, ignore_duplicates=True)
        if db.con.total_changes > previous:
            report["carriers_new"] += 1
        else:
            report["carriers_skipped"] += 1
    return report
