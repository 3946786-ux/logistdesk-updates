"""Извлечение текста и реквизитов из карточек и документов.

Любое распознавание предположительное: результат показывается человеку до записи.
Изображения не передаются в сеть и не сохраняются этим модулем.
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

from partner_registry import digits

DOCUMENT_FIELDS = {
    "partner": ("name", "inn", "kpp", "ogrn", "legal_address", "bank",
                "bik", "account", "corr_account", "phone", "email"),
    "driver": ("surname", "first_name", "patronymic", "birth_date",
               "passport_series", "passport_number", "passport_date",
               "passport_issued", "passport_department", "license_number",
               "license_categories", "license_date", "license_expires"),
    "vehicle": ("plate", "vin", "brand", "model", "year",
                "registration_series", "registration_number", "owner"),
}

FIELD_LABELS = {
    "name": "Название организации", "inn": "ИНН", "kpp": "КПП",
    "ogrn": "ОГРН / ОГРНИП", "legal_address": "Юридический адрес",
    "bank": "Банк", "bik": "БИК", "account": "Расчётный счёт",
    "corr_account": "Корреспондентский счёт", "phone": "Телефон",
    "email": "Электронная почта",
    "surname": "Фамилия", "first_name": "Имя", "patronymic": "Отчество",
    "birth_date": "Дата рождения", "passport_series": "Серия паспорта",
    "passport_number": "Номер паспорта", "passport_date": "Дата выдачи паспорта",
    "passport_issued": "Кем выдан", "passport_department": "Код подразделения",
    "license_number": "Номер ВУ", "license_categories": "Категории ВУ",
    "license_date": "Дата выдачи ВУ", "license_expires": "Срок действия ВУ",
    "plate": "Госномер", "vin": "VIN", "brand": "Марка",
    "model": "Модель", "year": "Год выпуска",
    "registration_series": "Серия СТС", "registration_number": "Номер СТС",
    "owner": "Собственник",
}


def kind_from_text(text: str) -> str:
    t = text.lower()
    if any(x in t for x in ("свидетельство о регистрации", "регистрации транспортного",
                          "vehicle registration", "vin", "гос. номер", "госномер")):
        return "vehicle"
    if any(x in t for x in ("водительское удостоверение", "driving licence",
                          "категории транспортных средств", "разрешенные категории")):
        return "driver"
    if any(x in t for x in ("паспорт гражданина", "паспорт российской федерации",
                          "код подразделения")):
        return "driver"
    return "partner"


def _value(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip(" \t:;,.-") if match else ""


def parse_text(text: str, kind: str | None = None) -> tuple[str, dict[str, str]]:
    """Возвращает предварительные поля, НИКОГДА не сохраняет их автоматически."""
    kind = kind if kind in DOCUMENT_FIELDS else kind_from_text(text)
    data: dict[str, str] = {}
    if kind == "partner":
        for field, pattern in {
            "inn": r"\bИНН\s*[:№]?\s*(\d{10,12})\b",
            "kpp": r"\bКПП\s*[:№]?\s*(\d{9})\b",
            "ogrn": r"\bОГРН(?:ИП)?\s*[:№]?\s*(\d{13,15})\b",
            "bik": r"\bБИК\s*[:№]?\s*(\d{9})\b",
            "account": r"(?:\bр[/\\.]?\s*с(?:ч)?\b|расч[её]тный\s+сч[её]т)\s*[:№]?\s*(\d{20})",
            "corr_account": r"(?:\bк[/\\.]?\s*с(?:ч)?\b|корр(?:еспондентский)?\s+сч[её]т)\s*[:№]?\s*(\d{20})",
            "email": r"([\w.+-]+@[\w.-]+\.[a-z]{2,})",
            "phone": r"(?:тел(?:ефон)?\.?\s*[:№]?\s*)?((?:\+7|8)[\d\s()\-]{10,20})",
        }.items():
            value = _value(text, pattern)
            if value:
                data[field] = value
        for field, pattern in {
            "name": r"((?:ООО|АО|ПАО|ИП|ОАО|ЗАО)\s*[«\"']?[^\n\r«»\"]{3,100}[»\"']?)",
            "legal_address": r"(?:юр(?:идический)?\.?\s*адрес)\s*[:\-]?\s*([^\n\r]+)",
            "bank": r"(?:наименование банка|банк)\s*[:\-]\s*([^\n\r]+)",
        }.items():
            value = _value(text, pattern)
            if value:
                data[field] = value
    elif kind == "vehicle":
        patterns = {
            "vin": r"\bVIN\s*[:№]?\s*([A-HJ-NPR-Z0-9]{17})\b",
            "plate": r"(?:гос(?:ударственный)?\.?\s*(?:рег(?:истрационный)?\.?\s*)?(?:знак|номер)|регистрационный\s+знак)\s*[:№]?\s*([А-ЯA-Z]\s?\d{3}\s?[А-ЯA-Z]{2}\s?\d{2,3})",
            "brand": r"(?:марка(?:\s+тс)?|марка,\s*модель)\s*[:\-]?\s*([^\n\r]+)",
            "year": r"(?:год\s+выпуска)\s*[:\-]?\s*(\d{4})",
            "owner": r"(?:собственник|владелец)\s*[:\-]?\s*([^\n\r]+)",
        }
        for field, pattern in patterns.items():
            value = _value(text, pattern)
            if value:
                data[field] = value
        # Номер и серия СТС не угадываются по произвольным числам.
        sts = _value(text, r"(?:серия\s*(?:и)?\s*номер\s*стс|свидетельство\s*№)\s*[:\-]?\s*(\d{2}\s?[А-ЯA-Z0-9]{2}\s*\d{6})")
        if sts:
            value = re.sub(r"\s", "", sts)
            data["registration_series"], data["registration_number"] = value[:4], value[4:]
    else:
        fio = _value(text, r"(?:фамилия\s*,?\s*имя\s*,?\s*отчество|фио)\s*[:\-]?\s*([А-ЯЁ][а-яё\-]+\s+[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+)?)")
        if fio:
            parts = fio.split()
            for field, value in zip(("surname", "first_name", "patronymic"), parts):
                data[field] = value
        # На фотографиях паспортов ФИО часто идёт тремя отдельными строками.
        for field, title in (("surname", "Фамилия"), ("first_name", "Имя"),
                             ("patronymic", "Отчество")):
            if field not in data:
                value = _value(text, rf"(?m)^\s*{title}\s*[:\-]?\s*([А-ЯЁ][А-ЯЁа-яё\-]+)\s*$")
                if value:
                    data[field] = value
        for field, pattern in {
            "birth_date": r"(?:дата\s+рождения)\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})",
            "passport_department": r"(?:код\s+подразделения)\s*[:\-]?\s*(\d{3}[- ]\d{3})",
            "license_categories": r"(?:категории?|category)\s*[:\-]?\s*([ABCDМE1,\s]{1,30})\b",
            "license_expires": r"(?:действител(?:ьно|ен)\s+до|срок\s+действия)\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})",
            "passport_issued": r"(?:кем\s+выдан)\s*[:\-]?\s*([^\n\r]+)",
        }.items():
            val = _value(text, pattern)
            if val:
                data[field] = val
        # Распознаём серию и номер только при явных подписях.
        series_number = re.search(
            r"серия\s*[:№]?\s*(\d{4})\s*номер\s*[:№]?\s*(\d{6})",
            text, re.IGNORECASE)
        if series_number:
            data["passport_series"] = series_number.group(1)
            data["passport_number"] = series_number.group(2)
        date_issued = _value(text, r"(?:дата\s+выдачи)\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})")
        if date_issued:
            data["passport_date"] = date_issued
        passport = _value(text, r"(?:паспорт\s*(?:серия)?\s*[:№]?\s*)(\d{2}\s?\d{2}\s?\d{6})")
        if passport:
            val = digits(passport)
            data["passport_series"], data["passport_number"] = val[:4], val[4:]
        license_no = _value(text, r"(?:водительское\s+удостоверение|в\/у)\s*[:№]?\s*(\d{2}\s?\d{2}\s?\d{6})")
        if license_no:
            data["license_number"] = digits(license_no)
        if "водительское удостоверение" in text.casefold():
            for field, marker in (("license_date", "4a"), ("license_expires", "4b")):
                value = _value(text, rf"(?m)^\s*{marker}\.?\s*[:\-]?\s*(\d{{2}}[./]\d{{2}}[./]\d{{4}})")
                if value:
                    data[field] = value
    return kind, data


def image_text(content: bytes) -> str:
    """Локальный OCR: сначала системный Windows OCR, затем Tesseract.

    Не загружает изображение на сервер и не записывает временных файлов.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("Не установлен модуль Pillow для обработки изображения") from exc
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    windows_error = ""
    if os.name == "nt":
        try:
            import winocr
            # Использует встроенный Windows.Media.Ocr. Для русского языка
            # должен быть доступен системный Language.OCR~~~ru-RU.
            result = winocr.recognize_pil_sync(image, "ru-RU")
            found = result.get("text", "") if isinstance(result, dict) else ""
            if found.strip():
                return found
        except (ImportError, RuntimeError, AssertionError, OSError, ValueError) as exc:
            windows_error = str(exc)
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "Windows OCR недоступен; резервный движок Tesseract тоже не установлен") from exc
    try:
        return pytesseract.image_to_string(image, lang="rus+eng", config="--psm 3")
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "Не найден движок OCR. Нужен русский OCR Windows или Tesseract rus+eng. "
            + (windows_error or "")) from exc
    except pytesseract.TesseractError as exc:
        raise RuntimeError("Распознавание не удалось: проверь русский языковой пакет OCR") from exc


def file_text(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Файл больше 20 МБ — уменьши размер")
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return image_text(path.read_bytes())
    if ext == ".txt":
        return path.read_text(encoding="utf-8-sig")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if len(reader.pages) > 20:
            raise ValueError("Слишком много страниц — максимум 20")
        content = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not content.strip():
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(str(path))
            lines = []
            try:
                for index in range(min(len(document), 20)):
                    page = document[index]
                    image = page.render(scale=2).to_pil()
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    lines.append(image_text(buffer.getvalue()))
                    page.close()
            finally:
                document.close()
            content = "\n".join(lines)
        if not content.strip():
            raise ValueError("В PDF не удалось распознать текст. Попробуй другой скан.")
        return content
    if ext == ".docx":
        from docx import Document
        document = Document(str(path))
        lines = [p.text for p in document.paragraphs]
        lines += [cell.text for t in document.tables for r in t.rows for cell in r.cells]
        return "\n".join(lines)
    if ext == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(str(path), read_only=True, data_only=True)
        try:
            rows = []
            for sheet in book.worksheets[:5]:
                for row in sheet.iter_rows(min_row=1, max_row=min(500, sheet.max_row or 500),
                                           max_col=min(30, sheet.max_column or 30),
                                           values_only=True):
                    rows.append(" ".join(str(v) for v in row if v is not None))
            return "\n".join(rows)
        finally:
            book.close()
    raise ValueError("Поддерживаются PDF, DOCX, XLSX, TXT и изображения. Для DOC/XLS пересохрани в новый формат")
