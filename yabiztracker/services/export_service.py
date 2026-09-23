from __future__ import annotations

import math
import os
import re
import tempfile
import zipfile
from urllib.parse import urlparse

from .xlsx_fallback import write_xlsx

# XML 1.0 illegal control characters. openpyxl handles some cases itself,
# but sanitising at the application boundary guarantees identical behaviour
# for both export engines.
_INVALID_XML_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")


def _clean_text(value) -> str:
    if value is None:
        return ""
    return _INVALID_XML_RE.sub("", str(value))


def _clean_number(value, default=0):
    try:
        value = float(value)
        if not math.isfinite(value):
            return default
        return int(value) if value.is_integer() else value
    except (TypeError, ValueError, OverflowError):
        return default


class ExportService:
    HEADERS = [
        "Название", "Адрес", "Населённый пункт", "Категория", "Возраст, дней",
        "Телефон", "E-mail", "Сайт", "Социальные сети", "Статус", "Комментарий",
        "Ответственный", "Дата следующего контакта", "Lead Score"
    ]
    WIDTHS = [34, 50, 24, 30, 14, 22, 30, 42, 50, 18, 45, 22, 22, 14]

    @staticmethod
    def social_text(raw):
        if not raw:
            return ""
        try:
            import json
            d = json.loads(raw) if isinstance(raw, str) else raw
            vals = []
            if isinstance(d, dict):
                for v in d.values():
                    vals.extend(v if isinstance(v, list) else [v])
            elif isinstance(d, list):
                vals = d
            return "; ".join(dict.fromkeys(
                _clean_text(x) for x in vals if x is not None and str(x)
            ))
        except Exception:
            return _clean_text(raw)

    @staticmethod
    def _safe_url(value):
        value = _clean_text(value).strip()
        if not value:
            return None
        try:
            p = urlparse(value)
            if p.scheme.lower() in ("http", "https") and p.netloc:
                # Excel external relationships cannot contain control chars.
                return value
        except Exception:
            pass
        return None

    @staticmethod
    def _normalise_org(o):
        category = _clean_text(o.get("category", ""))
        subcategory = _clean_text(o.get("subcategory", ""))
        if subcategory:
            category += " → " + subcategory

        return [
            _clean_text(o.get("name", "")),
            _clean_text(o.get("address", "")),
            _clean_text(o.get("city_name", "")),
            category,
            _clean_number(o.get("age_days", 0)),
            _clean_text(o.get("phone", "")),
            _clean_text(o.get("email", "")),
            _clean_text(o.get("website", "")),
            ExportService.social_text(o.get("social_links", "")),
            _clean_text(o.get("status", "Новый")) or "Новый",
            _clean_text(o.get("comment", "")),
            _clean_text(o.get("responsible", "")),
            _clean_text(o.get("next_contact_date", "")),
            _clean_number(o.get("score", 0)),
        ]

    @staticmethod
    def _validate_xlsx(path):
        """
        Validate the actual bytes which are about to be delivered.

        Validation has two independent layers:
        1. ZIP + XML well-formedness and required OPC parts.
        2. openpyxl round-trip, when available.
        """
        with zipfile.ZipFile(path, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"Повреждённый XLSX ZIP: {bad}")

            names = set(archive.namelist())
            required = {
                "[Content_Types].xml",
                "_rels/.rels",
                "xl/workbook.xml",
                "xl/_rels/workbook.xml.rels",
                "xl/worksheets/sheet1.xml",
            }
            missing = required - names
            if missing:
                raise ValueError(
                    "В XLSX отсутствуют обязательные части: "
                    + ", ".join(sorted(missing))
                )

            # Parse every XML/rels part. This catches invalid XML characters,
            # malformed relationships and truncated XML.
            import xml.etree.ElementTree as ET
            for name in names:
                if name.endswith(".xml") or name.endswith(".rels"):
                    ET.fromstring(archive.read(name))

        try:
            from openpyxl import load_workbook
        except ModuleNotFoundError:
            return

        wb = load_workbook(path, read_only=True, data_only=False)
        try:
            if "Организации" not in wb.sheetnames:
                raise ValueError("В XLSX отсутствует лист «Организации»")
            ws = wb["Организации"]
            # Force worksheet XML parsing, including hyperlinks/relationships.
            _ = ws.max_row
            _ = ws.max_column
            for _ in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 3)):
                pass
        finally:
            wb.close()

    @staticmethod
    def _atomic_replace(path, writer):
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)

        fd, tmp = tempfile.mkstemp(
            prefix=".sbm_export_", suffix=".xlsx", dir=directory
        )
        os.close(fd)

        try:
            writer(tmp)
            ExportService._validate_xlsx(tmp)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _openpyxl_writer(self, rows, links, headers, widths):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter

        def writer(tmp):
            wb = Workbook()
            ws = wb.active
            ws.title = "Организации"

            ws.append(headers)
            for cell in ws[1]:
                cell.font = Font(bold=True)

            for row in rows:
                ws.append(row)

            for i, width in enumerate(widths, 1):
                ws.column_dimensions[get_column_letter(i)].width = width

            ws.freeze_panes = "A2"
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"

            for ref, url in links.items():
                ws[ref].hyperlink = url
                ws[ref].style = "Hyperlink"

            wb.save(tmp)

        return writer

    def _fallback_writer(self, rows, links, headers, widths):
        return lambda tmp: write_xlsx(
            tmp, headers, rows, links, widths
        )

    def export(self, path, orgs, columns=None):
        """
        Export is deliberately fail-safe:
        - normal engine: openpyxl;
        - if openpyxl is absent OR fails validation, standard-library writer;
        - the destination file is replaced only after complete validation.

        Thus a failed export can never leave a half-written/corrupt target file.
        """
        if columns is None:
            columns = list(range(len(self.HEADERS)))
        try:
            columns = [int(i) for i in columns]
        except (TypeError, ValueError):
            raise ValueError("Некорректный список столбцов для экспорта")
        if not columns:
            raise ValueError("Не выбран ни один столбец для экспорта")
        if len(set(columns)) != len(columns) or any(i < 0 or i >= len(self.HEADERS) for i in columns):
            raise ValueError("Некорректный список столбцов для экспорта")

        all_rows = [self._normalise_org(o) for o in orgs]
        rows = [[row[i] for i in columns] for row in all_rows]
        headers = [self.HEADERS[i] for i in columns]
        widths = [self.WIDTHS[i] for i in columns]

        links = {}
        website_index = self.HEADERS.index("Сайт")
        if website_index in columns:
            export_col = columns.index(website_index) + 1
            col_letter = ""
            n = export_col
            while n:
                n, rem = divmod(n - 1, 26)
                col_letter = chr(65 + rem) + col_letter
            for row_number, org in enumerate(orgs, 2):
                url = self._safe_url(org.get("website", ""))
                if url:
                    links[f"{col_letter}{row_number}"] = url

        errors = []

        try:
            from openpyxl import Workbook  # noqa: F401
            self._atomic_replace(
                path, self._openpyxl_writer(rows, links, headers, widths)
            )
            return "openpyxl"
        except Exception as exc:
            errors.append(f"openpyxl: {exc}")

        # A second, independent implementation is used if the preferred
        # engine is unavailable or cannot create a valid package.
        try:
            self._atomic_replace(
                path, self._fallback_writer(rows, links, headers, widths)
            )
            return "fallback"
        except Exception as exc:
            errors.append(f"fallback: {exc}")

        raise RuntimeError(
            "Не удалось создать корректный файл Excel. "
            + " | ".join(errors)
        )
