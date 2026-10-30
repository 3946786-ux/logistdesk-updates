"""Synthetic-only regression tests: no actual ATI accounts or customer data."""
import sqlite3
import unittest
from ati_import21 import parse_ati_text, AtiImportLedger

SAMPLE = """Ваши грузы   Добавить груз   Все площадки   Фильтры
#РХС111038
RUS
1398 км
Череповец
Вологодская область
близ. крупные города
готов 30 окт - 4 ноя
Елабуга г.
Республика Татарстан
20 т / 92 м³ ТНП
тент.
загр/выгр: бок.
отд.машина.
180 000 ₽ с НДС 22% (128,8 руб/км)
без торга
Череповец (30 окт - 4 ноя) → Елабуга г.
Анна
Поднять груз в ТОП поиска
#РХС111145
RUS
Череповец
Вологодская область
готов 30 окт - 4 ноя
Набережные Челны
Республика Татарстан
20 т / 92 м³ ТНП
тент.
180 000 ₽ с НДС 22%
Череповец (30 окт - 4 ноя) → Набережные Челны
Стелс вкл.
#РХС111469
RUS
Набережные Челны
Республика Татарстан
готов 30 - 31 окт
Ростов-на-Дону
Ростовская область
20 т / 92 м³ ТНП
тент.
190 000 ₽ с НДС 22%
Набережные Челны (30-31 окт) → Ростов-на-Дону
"""


class FakeDb:
    def __init__(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE routes (id TEXT PRIMARY KEY, origin TEXT, destination TEXT, note TEXT)")
        self.saved = []

    def next_route_id(self):
        return "R%03d" % (len(self.saved) + 1)

    def save_route(self, record, replace=False):
        assert not replace
        self.saved.append(record)
        with self.con:
            self.con.execute("INSERT INTO routes VALUES(?,?,?,?)",
                             (record["id"], record["origin"], record["destination"], record["note"]))


class AtiImportTests(unittest.TestCase):
    def test_three_loads_with_page_noise(self):
        loads = parse_ati_text(SAMPLE)
        self.assertEqual(3, len(loads))
        self.assertEqual(("Череповец", "Елабуга"), (loads[0].origin, loads[0].destination))
        self.assertEqual(("Череповец", "Набережные Челны"), (loads[1].origin, loads[1].destination))
        self.assertEqual(("Набережные Челны", "Ростов-на-Дону"), (loads[2].origin, loads[2].destination))
        self.assertEqual("20 т", loads[0].weight)
        self.assertEqual("92 м³", loads[0].volume)
        self.assertEqual(180000, loads[0].rate_rub)
        self.assertIn("30 окт", loads[0].date_window)
        self.assertIn("НДС", loads[0].vat)

    def test_missing_cities_never_committed(self):
        loads = parse_ati_text("#РХС111222\n20 т 90 м³\n180 000 ₽")
        self.assertTrue(loads[0].warnings)
        with self.assertRaises(ValueError):
            loads[0].to_route()

    def test_no_load_ids_ignores_unrelated_page(self):
        self.assertEqual([], parse_ati_text("Ваши грузы, поиск, фильтры, кнопки и номера 123456"))

    def test_repeated_id_deduplicated(self):
        self.assertEqual(1, len(parse_ati_text(SAMPLE.split("#РХС111145")[0] * 2)))

    def test_copies_preserve_existing_records(self):
        db = FakeDb()
        ledger = AtiImportLedger(db)
        load = parse_ati_text(SAMPLE)[0]
        route, created = ledger.import_load(load)
        self.assertTrue(created)
        self.assertEqual("R001", route)
        load.origin = "Неправильный город"
        route2, created2 = ledger.import_load(load)
        self.assertFalse(created2)
        self.assertEqual(route, route2)
        self.assertEqual(1, len(db.saved))
        self.assertEqual("Череповец", db.con.execute("SELECT origin FROM routes").fetchone()[0])

    def test_vat_not_assumed(self):
        load = parse_ati_text("#РХС1234567\nКазань → Москва\n120 000 ₽")[0]
        self.assertIsNone(load.to_route()["with_vat"])

    def test_one_cargo_from_detail_copy(self):
        content = """Открыть груз
Груз №РХС998877
Казань → Екатеринбург
10 т / 35 м³
тент
150 000 ₽
"""
        loads = parse_ati_text(content)
        self.assertEqual(1, len(loads))
        self.assertEqual("Казань", loads[0].origin)
        self.assertEqual("Екатеринбург", loads[0].destination)
        self.assertEqual("РХС998877", loads[0].ati_id)

    def test_adr_class_8_and_un_number_are_read_without_guesswork(self):
        content = """#РХС889900
Нижнекамск → Уфа
20 т / 82 м³
ADR класс 8
UN 1760
170 000 ₽
"""
        load = parse_ati_text(content)[0]
        self.assertTrue(load.adr_mentioned)
        self.assertEqual("8", load.adr_class)
        self.assertEqual("1760", load.un_number)
        note = load.to_route()["note"]
        self.assertIn("ADR класс: 8", note)
        self.assertIn("UN: 1760", note)

    def test_adr_without_class_requires_verification(self):
        load = parse_ati_text("#РХС889901\nКазань → Москва\nОпасный груз ADR\n")[0]
        self.assertTrue(load.adr_mentioned)
        self.assertEqual("", load.adr_class)
        self.assertTrue(any("ADR упомянут" in x for x in load.warnings))

    def test_no_adr_is_inferred_from_ordinary_cargo(self):
        load = parse_ati_text("#РХС889902\nКазань → Москва\nКраска, 3 т\n")[0]
        self.assertFalse(load.adr_mentioned)
        self.assertEqual("", load.adr_class)
        self.assertEqual("", load.un_number)

    def test_un_alone_is_not_an_adr_class(self):
        load = parse_ati_text("#РХС889903\nКазань → Москва\nUN 1263\n")[0]
        self.assertEqual("1263", load.un_number)
        self.assertEqual("", load.adr_class)
        self.assertTrue(any("Указан UN" in x for x in load.warnings))

    def test_oversized_input_rejected(self):
        with self.assertRaises(ValueError):
            parse_ati_text("x" * 1_500_001)


if __name__ == "__main__":
    unittest.main()
