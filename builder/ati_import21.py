"""Offline, read-only ATI.SU clipboard importer for LogistDesk 2.1.

The only input is text explicitly pasted by the user; no browser/API access.
Never guess missing fields or overwrite existing routes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

ANCHOR = re.compile(r"(?im)(?<!\w)(?:[#№]\s*|\bгруз\s*№\s*)(?P<id>(?:[РP][ХX][СC]|RXC)\s*\d{4,12}|\d{7,12})(?!\w)")
ARROW = re.compile(r"(?m)^\s*(?:[☷•→-]\s*)?(?P<left>[^\n→➜]{2,95}?)\s*(?:→|➜|->|⇒)\s*(?P<right>[^\n]{2,100})\s*$")
WEIGHT = re.compile(r"(?<!\w)(\d{1,3}(?:[.,]\d{1,3})?)\s*(?:т(?:онн)?\b)", re.I)
VOLUME = re.compile(r"(?<!\w)(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:м\s*(?:[³3]|\^3)|куб\.?\s*м)", re.I)
RATE = re.compile(r"(?<![\d,])((?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d{4,8}))\s*(?:₽|руб\.?|р\b)", re.I)
DATE = re.compile(r"\b(?:готов(?:\s+с)?|загрузк[аи]?|погрузк[аи]?)\s*[:\-]?\s*(\d{1,2}\s+[а-яё]{3,10}(?:\s*[-–—]\s*\d{1,2}\s+[а-яё]{3,10})?(?:\s+20\d{2}\s*г?\.? )?)", re.I)
CITY_LINE = re.compile(r"^[А-ЯЁ][а-яёА-ЯЁ .\-]{2,55}$")
EXCLUDE = re.compile(r"\b(?:област[ьи]|республик[аи]|край|район|близ\.?|город[аов]*|готов|договор|направл|погруз|выгруз|загруз|тент|борт|руб|ставк|скидк|торг|встречн|предлож|страхов|комментар|показ|фильтр|отд|машин|срок|контакт|россия)\b", re.I)
MAX_TEXT = 1_500_000
MAX_LOADS = 250
ADR_CLASS = re.compile(
    r"(?i)(?:\bADR\b|\bАДР\b)\s*(?:[:№-]?\s*(?:класс(?:а)?\s*)?)?([1-9](?:\.\d{1,2})?)(?!\d)"
)
UN_NUMBER = re.compile(r"(?i)\b(?:UN|ООН)\s*(?:№\s*)?[:#-]?\s*(\d{4})(?!\d)")
ADR_MENTION = re.compile(r"(?i)\b(?:ADR|АДР)\b|\bопасн(?:ый|ого|ые)\s+груз")


@dataclass
class AtiLoad:
    ati_id: str
    origin: str = ""
    destination: str = ""
    weight: str = ""
    volume: str = ""
    body: str = ""
    loading: str = ""
    date_window: str = ""
    rate_rub: int | None = None
    vat: str = ""
    bargaining: str = ""
    adr_mentioned: bool = False
    adr_class: str = ""
    un_number: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_route(self) -> dict:
        """Only map fields actually observed on ATI; no phantom sender or date."""
        if not self.origin or not self.destination:
            raise ValueError("Укажи оба города перед сохранением")
        meta = [f"ATI №{self.ati_id}"]
        if self.body:
            meta.append("Кузов: " + self.body)
        if self.rate_rub is not None:
            meta.append(f"Ставка ATI: {self.rate_rub} ₽" + (f" ({self.vat})" if self.vat else ""))
        if self.bargaining:
            meta.append(self.bargaining)
        if self.adr_class:
            meta.append("ADR класс: " + self.adr_class)
        elif self.adr_mentioned:
            meta.append("ADR: указан, класс не подтверждён")
        if self.un_number:
            meta.append("UN: " + self.un_number)
        return {
            "origin": self.origin,
            "destination": self.destination,
            "weight": " / ".join(x for x in [self.weight, self.volume] if x),
            "loading": self.loading,
            "date_window": self.date_window,
            "with_vat": self.rate_rub if self.vat.lower().startswith("с ндс") else None,
            "status": "Выложен",
            "note": "; ".join(meta),
        }


def _clean_city(value: str) -> str:
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\b(?:г\.|город)\s*", "", value, flags=re.I)
    value = re.sub(r"\s+(?:г\.)\s*$", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" \u00a0,;|—–-•")
    return value


def _cities(block: str) -> tuple[str, str]:
    # ATI often includes its own compact route line with an arrow. Prefer that
    # over columns and over regional labels.
    for match in reversed(list(ARROW.finditer(block))):
        left, right = _clean_city(match["left"]), _clean_city(match["right"])
        left = re.sub(r"^.{0,25}?\b(?:RUS|загрузка)\s*[:\-]?\s*", "", left, flags=re.I)
        right = re.split(r"\s{2,}|\s+\d{1,2}\s+[а-яё]{3}", right, maxsplit=1)[0].strip()
        if 2 <= len(left) <= 70 and 2 <= len(right) <= 70 and not EXCLUDE.search(left+" "+right):
            return left, right
    options: list[str] = []
    # Fallback: first two city-looking lines before technical specs. This
    # deliberately refuses to invent city values for single-line dumps.
    for raw in block.splitlines():
        line = _clean_city(raw)
        if not CITY_LINE.fullmatch(line) or EXCLUDE.search(line) or any(ch.isdigit() for ch in line):
            continue
        if line.upper() in {"RUS", "АННА", "КОНТАКТЫ", "НДС", "ТИП"}:
            continue
        if not options or line.casefold() != options[-1].casefold():
            options.append(line)
        if len(options) >= 2:
            return options[0], options[1]
    return "", ""


def _parse_block(ati_id: str, block: str) -> AtiLoad:
    load = AtiLoad(ati_id=ati_id)
    load.origin, load.destination = _cities(block)
    m = WEIGHT.search(block)
    if m:
        load.weight = m[1].replace(",", ".") + " т"
    m = VOLUME.search(block)
    if m:
        load.volume = m[1].replace(",", ".") + " м³"
    m = RATE.search(block)
    if m:
        load.rate_rub = int(re.sub(r"\D", "", m[1]))
    m = DATE.search(block)
    if m:
        load.date_window = m[1].strip().rstrip(".")
    m = re.search(r"\b(?:тент|рефрижератор|изотерм|борт|фургон|контейнер|площадка|трал)\b", block, flags=re.I)
    if m:
        load.body = m[0]
    m = re.search(r"(?:загр\s*/\s*выгр|загрузка\s*/\s*выгрузка|загр|выгр)\s*[:.]?\s*([^\n]{2,65})", block, flags=re.I)
    if m:
        load.loading = m[1].strip(" .,;")
    vat = re.search(r"\b(?:с\s+НДС(?:\s*\d{1,2}\s*%)?|без\s+НДС)\b", block, re.I)
    if vat:
        load.vat = vat[0].strip()
    if re.search(r"\bбез\s+торга\b", block, re.I):
        load.bargaining = "без торга"
    elif re.search(r"\bторг\b", block, re.I):
        load.bargaining = "торг"
    load.adr_mentioned = bool(ADR_MENTION.search(block))
    match_adr = ADR_CLASS.search(block)
    if match_adr:
        load.adr_class = match_adr[1]
        load.adr_mentioned = True
    match_un = UN_NUMBER.search(block)
    if match_un:
        load.un_number = match_un[1]
    if load.adr_mentioned and not load.adr_class:
        load.warnings.append("ADR упомянут, но класс не распознан — проверь")
    if load.un_number and not load.adr_mentioned:
        load.warnings.append("Указан UN, но ADR/класс не найдены — проверь")
    if not load.origin or not load.destination:
        load.warnings.append("Не удалось уверенно определить города — проверь вручную")
    if not load.date_window:
        load.warnings.append("Дата загрузки не распознана")
    if load.rate_rub is None:
        load.warnings.append("Ставка не распознана")
    return load


def parse_ati_text(text: str) -> list[AtiLoad]:
    """Parse one user-pasted ATI cargo card (or optionally several).

    Unrelated browser menus are ignored. The ATI cargo ID must be included
    for duplicate prevention; no invented ID or registration is attempted.

    Never connect to ATI or make background HTTP requests. Duplicate ATI IDs
    in the same clipboard return a single preview card.
    """
    if not isinstance(text, str):
        raise TypeError("Ожидается текст из буфера обмена")
    if len(text) > MAX_TEXT:
        raise ValueError("Слишком много текста; скопируй карточку одного груза ATI")
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\r\n", "\n")
    matches = list(ANCHOR.finditer(text))
    if len(matches) > MAX_LOADS:
        raise ValueError("Слишком много грузов — импортируй страницу частями")
    seen: set[str] = set()
    out: list[AtiLoad] = []
    for i, match in enumerate(matches):
        key = re.sub(r"\s+", "", match["id"]).upper()
        if key in seen:
            continue
        seen.add(key)
        body = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
        out.append(_parse_block(key, body))
    return out


class AtiImportLedger:
    """Local idempotency ledger. Explicitly selected loads only, no updates."""

    def __init__(self, db):
        self.db = db
        with db.con:
            db.con.execute("""
                CREATE TABLE IF NOT EXISTS ati_import21 (
                    ati_id TEXT PRIMARY KEY,
                    route_id TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def existing(self, ids: Iterable[str]) -> dict[str, str]:
        result = {}
        for raw_id in ids:
            ati_id = re.sub(r"\s+", "", raw_id).upper()
            row = self.db.con.execute(
                "SELECT route_id FROM ati_import21 WHERE ati_id=?", (ati_id,)).fetchone()
            if row:
                result[ati_id] = str(row[0])
        return result

    def import_load(self, load: AtiLoad) -> tuple[str, bool]:
        key = re.sub(r"\s+", "", load.ati_id).upper()
        previous = self.existing([key])
        if key in previous:
            return previous[key], False
        route = load.to_route()  # validate before touching database
        route_id = self.db.next_route_id()
        route["id"] = route_id
        self.db.save_route(route, replace=False)
        with self.db.con:
            self.db.con.execute(
                "INSERT INTO ati_import21(ati_id,route_id) VALUES(?,?)", (key, route_id))
        return route_id, True
