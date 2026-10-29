"""Читаем разные виды документов и не сохраняем ПДн без проверки."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_extract import file_text, kind_from_text, parse_text


class DocumentTests(unittest.TestCase):
    def test_passport_ocr_with_separate_name_lines(self):
        sample = ("ПАСПОРТ ГРАЖДАНИНА РОССИЙСКОЙ ФЕДЕРАЦИИ\n"
                  "Фамилия\nИВАНОВ\nИмя\nИВАН\nОтчество\nИВАНОВИЧ\n"
                  "Дата рождения: 12.03.1985\nКод подразделения 123-456\n"
                  "Серия 1234 Номер 567890\nДата выдачи: 24.06.2010")
        kind, data = parse_text(sample)
        self.assertEqual(kind, "driver")
        self.assertEqual(data.get("surname"), "ИВАНОВ")
        self.assertEqual(data.get("first_name"), "ИВАН")
        self.assertEqual(data.get("passport_series"), "1234")
        self.assertEqual(data.get("passport_number"), "567890")
        self.assertEqual(data.get("passport_date"), "24.06.2010")

    def test_license_labeled_dates(self):
        sample = ("ВОДИТЕЛЬСКОЕ УДОСТОВЕРЕНИЕ\n"
                  "4a. 01.01.2021\n4b. 01.01.2031\n"
                  "Категории: B, C, CE\n")
        kind, data = parse_text(sample)
        self.assertEqual(kind, "driver")
        self.assertEqual(data.get("license_date"), "01.01.2021")
        self.assertEqual(data.get("license_expires"), "01.01.2031")

    def test_vehicle_vin(self):
        kind, data = parse_text("СВИДЕТЕЛЬСТВО О РЕГИСТРАЦИИ ТС\nVIN: XTA210990Y1234567")
        self.assertEqual(kind, "vehicle")
        self.assertEqual(data.get("vin"), "XTA210990Y1234567")

    def test_plain_txt_card(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "card.txt"
            p.write_text("ООО Вектор\nИНН: 1650123456", encoding="utf-8")
            kind, data = parse_text(file_text(p))
            self.assertEqual(kind, "partner")
            self.assertEqual(data.get("inn"), "1650123456")

    def test_scanned_pdf_uses_local_raster_ocr(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "scan.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=220, height=300)
            with p.open("wb") as stream:
                writer.write(stream)
            with patch("document_extract.image_text", return_value="ИНН: 1650123456") as engine:
                result = file_text(p)
                engine.assert_called()
            self.assertIn("1650123456", result)


if __name__ == "__main__":
    unittest.main()
