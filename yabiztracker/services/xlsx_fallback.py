from __future__ import annotations

import math
import re
import zipfile
from xml.sax.saxutils import escape, quoteattr

# ECMA-376 SpreadsheetML namespace.
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# XML 1.0 does not permit C0 control characters except TAB/LF/CR.
_INVALID_XML_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")


def _xml_text(value) -> str:
    """Return text that is always legal XML 1.0 character data."""
    if value is None:
        return ""
    text = str(value)
    return _INVALID_XML_RE.sub("", text)


def _safe_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            if math.isfinite(float(value)):
                return value
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _col(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _cell(ref: str, value) -> str:
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'

    number = _safe_number(value)
    if number is not None:
        # Avoid scientific/locale-dependent representations.
        if isinstance(number, int):
            text = str(number)
        else:
            text = repr(float(number))
        return f'<c r="{ref}" t="n"><v>{text}</v></c>'

    text = escape(_xml_text(value), {'"': "&quot;"})
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _safe_url(value) -> str:
    # URL was already validated by ExportService. Here we only guarantee
    # XML-safe characters because URLs are stored in a .rels XML part.
    return _xml_text(value).strip()


def write_xlsx(path, headers, rows, hyperlinks=None, widths=None):
    """
    Create a conservative, standards-compliant XLSX package using only the
    Python standard library.

    The writer intentionally uses inline strings and a single worksheet.
    This avoids sharedStrings/styles relationships that are unnecessary for
    an export and are common sources of broken OPC packages.
    """
    hyperlinks = hyperlinks or {}
    widths = list(widths or [20] * len(headers))
    headers = list(headers)
    rows = [list(r) for r in rows]

    max_col = len(headers)
    data = [headers] + rows
    max_row = len(data)

    sheet = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">',
        '<sheetPr/>',
        '<dimension ref="A1:%s%d"/>' % (_col(max_col), max_row),
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        '</sheetView></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        '<cols>',
    ]

    for i in range(1, max_col + 1):
        width = widths[i - 1] if i - 1 < len(widths) else 20
        try:
            width = max(5.0, min(float(width), 255.0))
        except (TypeError, ValueError):
            width = 20.0
        sheet.append(
            f'<col min="{i}" max="{i}" width="{width:.2f}" customWidth="1"/>'
        )
    sheet.append("</cols>")
    sheet.append("<sheetData>")

    for r, row in enumerate(data, 1):
        sheet.append(f'<row r="{r}">')
        for c in range(1, max_col + 1):
            value = row[c - 1] if c - 1 < len(row) else ""
            sheet.append(_cell(f"{_col(c)}{r}", value))
        sheet.append("</row>")
    sheet.append("</sheetData>")

    if max_row and max_col:
        sheet.append(f'<autoFilter ref="A1:{_col(max_col)}{max_row}"/>')

    clean_links = {}
    for ref, url in hyperlinks.items():
        clean_url = _safe_url(url)
        if clean_url:
            clean_links[str(ref)] = clean_url

    if clean_links:
        sheet.append("<hyperlinks>")
        for i, ref in enumerate(clean_links, 1):
            sheet.append(
                f'<hyperlink ref={quoteattr(str(ref))} r:id={quoteattr("rId" + str(i))}/>'
            )
        sheet.append("</hyperlinks>")

    sheet.append("</worksheet>")
    sheet_xml = "".join(sheet)

    # Worksheet relationships. Keep IDs local to this relationships part.
    sheet_rels = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<Relationships xmlns="{PKG_REL_NS}">',
    ]
    for i, url in enumerate(clean_links.values(), 1):
        sheet_rels.append(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target={quoteattr(url)} TargetMode="External"/>'
        )
    sheet_rels.append("</Relationships>")
    sheet_rels_xml = "".join(sheet_rels)

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
        "<sheets>"
        f'<sheet name={quoteattr(_xml_text("Организации"))} sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml)
        z.writestr("_rels/.rels", root_rels_xml)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if clean_links:
            z.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels_xml)
