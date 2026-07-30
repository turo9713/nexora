"""Safe, deterministic renderers for task-result document artifacts.

The renderers operate entirely in memory, never execute user content, never
resolve user-provided paths, and produce only allowlisted non-executable
formats.  Rich formats are derived from the already-redacted task title and
result summary supplied by :mod:`nexora.storage.artifacts`.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from .artifact_content import ContentBlock, parse_artifact_content


DOCUMENT_FORMATS = ("docx", "pdf")
SPREADSHEET_HINTS = (
    "xlsx", "excel", "spreadsheet", "таблиц", "бюджет", "смет", "метрик",
    "аналитик", "финансов", "расход", "доход",
)
ARCHIVE_HINTS = (
    "zip", "archive", "архив", "пакет файлов", "исходник", "исходн",
    "проект с файлами", "комплект файлов",
)
ASSET_ROOT = Path(__file__).with_name("assets")
PDF_FONT = ASSET_ROOT / "DejaVuSans.ttf"


class DocumentRenderError(RuntimeError):
    """A rich document could not be rendered safely."""


def selected_formats(title: str, result: str) -> tuple[str, ...]:
    """Return deterministic formats for a completed task.

    DOCX and PDF are useful safe defaults for every completed task. XLSX and
    ZIP are opt-in based on explicit task/result intent to avoid producing
    misleading spreadsheets or archives.
    """

    haystack = f"{title}\n{result[:4000]}".casefold()
    formats = list(DOCUMENT_FORMATS)
    if any(value in haystack for value in SPREADSHEET_HINTS):
        formats.append("xlsx")
    if any(value in haystack for value in ARCHIVE_HINTS):
        formats.append("zip")
    return tuple(formats)


def required_artifact_formats(title: str, result: str) -> tuple[str, ...]:
    """Return every artifact kind required before a task may complete."""

    return ("markdown", "json", *selected_formats(title, result))


def _plain_lines(value: str) -> list[str]:
    lines = []
    for raw in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw).strip()
        if line:
            lines.append(line[:4000])
    return lines or ["Результат не содержит отображаемого текста."]


def _clean_spreadsheet_text(value: Any) -> str:
    text = re.sub(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",
        "",
        str(value or ""),
    )
    return text.strip()[:32_000]


def render_docx(task: dict[str, Any]) -> bytes:
    """Render a polished Word business brief using the pinned python-docx."""

    try:
        from docx import Document
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches, Pt, RGBColor, Twips
    except ImportError as exc:  # pragma: no cover - deployment dependency gate
        raise DocumentRenderError("DOCX renderer dependency is unavailable") from exc

    title = str(task["title"])
    task_id = str(task["task_id"])
    result = str(task["result"])
    content = parse_artifact_content(result)
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    def set_font(run: Any, size: float, *, bold: bool = False, color: str = "1F2937") -> None:
        run.font.name = "Calibri"
        run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Calibri")
        run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Calibri")
        run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Calibri")
        run.font.size = Pt(size)
        run.bold = bold
        run.font.color.rgb = RGBColor.from_string(color)

    def set_table_geometry(table: Any, widths_dxa: list[int]) -> None:
        table.autofit = False
        for index, width in enumerate(widths_dxa):
            table.columns[index].width = Twips(width)
        for row in table.rows:
            for index, cell in enumerate(row.cells):
                width = widths_dxa[min(index, len(widths_dxa) - 1)]
                cell.width = Twips(width)

    def shade_cell(cell: Any, color: str) -> None:
        properties = cell._tc.get_or_add_tcPr()
        existing = properties.find(qn("w:shd"))
        if existing is not None:
            properties.remove(existing)
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), color)
        insertion_index = next(
            (
                index
                for index, child in enumerate(properties)
                if child.tag
                in {
                    qn("w:noWrap"),
                    qn("w:tcMar"),
                    qn("w:textDirection"),
                    qn("w:tcFitText"),
                    qn("w:vAlign"),
                    qn("w:hideMark"),
                    qn("w:headers"),
                }
            ),
            len(properties),
        )
        properties.insert(insertion_index, shading)

    def add_content_table(rows: list[ContentBlock]) -> None:
        column_count = max(len(row.cells) for row in rows)
        table = document.add_table(rows=len(rows), cols=column_count)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.style = "Table Grid"
        for row_index, block in enumerate(rows):
            for column_index in range(column_count):
                cell = table.rows[row_index].cells[column_index]
                value = block.cells[column_index] if column_index < len(block.cells) else ""
                cell.text = value
                if block.kind == "table_header":
                    cell.paragraphs[0].runs[0].bold = True
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.05
    for style_name, size, before, after, color in (
        ("Heading 1", 16, 16, 8, "2E74B5"),
        ("Heading 2", 13, 12, 6, "2E74B5"),
        ("Heading 3", 12, 8, 4, "1F4D78"),
    ):
        style = document.styles[style_name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    set_font(header.add_run("NEXORA · РЕЗУЛЬТАТ ЗАДАЧИ"), 9, bold=True, color="6B7280")
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_font(footer.add_run(f"{task_id} · Generated by Nexora"), 8.5, color="6B7280")

    kicker = document.add_paragraph()
    kicker.paragraph_format.space_after = Pt(2)
    set_font(kicker.add_run("NEXORA RESULT"), 9, bold=True, color="2E74B5")
    title_paragraph = document.add_paragraph()
    title_paragraph.paragraph_format.space_after = Pt(8)
    set_font(title_paragraph.add_run(title), 23, bold=True, color="111827")
    subtitle = document.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(14)
    set_font(subtitle.add_run("Безопасный итог выполнения задачи"), 12, color="4B5563")

    table = document.add_table(rows=3, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for row, (label, value) in zip(
        table.rows,
        (
            ("Task ID", task_id),
            ("Status", "COMPLETED"),
            ("Completed", str(task.get("completed_at") or "—")[:32]),
        ),
    ):
        for index in range(2):
            row.cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_font(row.cells[0].paragraphs[0].add_run(label), 10, bold=True, color="374151")
        set_font(row.cells[1].paragraphs[0].add_run(value), 10, color="111827")
    shade_cell(table.rows[0].cells[0], "F2F4F7")
    set_table_geometry(table, [2700, 6660])

    document.add_heading("Результат", level=1)
    index = 0
    deferred_tables: list[list[ContentBlock]] = []
    while index < len(content.blocks):
        block = content.blocks[index]
        if block.kind in {"table_header", "table_row"}:
            table_rows = [block]
            column_count = len(block.cells)
            index += 1
            while (
                index < len(content.blocks)
                and content.blocks[index].kind in {"table_header", "table_row"}
                and len(content.blocks[index].cells) == column_count
            ):
                table_rows.append(content.blocks[index])
                index += 1
            deferred_tables.append(table_rows)
            continue
        if block.kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.left_indent = Inches(0.5)
            paragraph.paragraph_format.first_line_indent = Inches(-0.25)
            paragraph.paragraph_format.space_after = Pt(5)
            set_font(paragraph.add_run(block.text), 11)
        elif block.kind == "numbered":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Inches(0.5)
            paragraph.paragraph_format.first_line_indent = Inches(-0.25)
            paragraph.paragraph_format.space_after = Pt(5)
            set_font(paragraph.add_run(f"{block.label}.  "), 11, bold=True)
            set_font(paragraph.add_run(block.text), 11)
        elif block.kind == "heading":
            if not (
                index + 1 < len(content.blocks)
                and content.blocks[index + 1].kind in {"table_header", "table_row"}
            ):
                document.add_heading(
                    block.text,
                    level=max(1, min(3, block.level)),
                )
        elif block.kind == "key_value":
            paragraph = document.add_paragraph()
            set_font(paragraph.add_run(f"{block.label}: "), 11, bold=True)
            set_font(paragraph.add_run(block.text), 11)
        else:
            paragraph = document.add_paragraph()
            set_font(paragraph.add_run(block.text), 11)
        index += 1

    if deferred_tables:
        for rows in deferred_tables:
            table_label = document.add_paragraph()
            table_label.paragraph_format.space_before = Pt(10)
            table_label.paragraph_format.space_after = Pt(4)
            set_font(
                table_label.add_run(rows[0].section),
                12,
                bold=True,
                color="2E74B5",
            )
            add_content_table(rows)

    properties = document.core_properties
    properties.title = title[:255]
    properties.subject = "Nexora task result"
    properties.author = "Nexora"
    properties.keywords = "Nexora, task result"
    output = io.BytesIO()
    document.save(output)
    payload = output.getvalue()
    _verify_ooxml(payload, "word/")
    return payload


def render_pdf(task: dict[str, Any]) -> bytes:
    """Render a Cyrillic-safe PDF with an embedded redistributable font."""

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover - deployment dependency gate
        raise DocumentRenderError("PDF renderer dependency is unavailable") from exc
    if not PDF_FONT.is_file():
        raise DocumentRenderError("PDF font asset is unavailable")

    content = parse_artifact_content(str(task["result"]))
    font_name = "NexoraDejaVu"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(PDF_FONT)))
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=LETTER,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.68 * inch,
        bottomMargin=0.68 * inch,
        title=str(task["title"])[:255],
        author="Nexora",
        subject="Nexora task result",
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "NexoraBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=12.5,
        spaceAfter=5,
        textColor=colors.HexColor("#1F2937"),
    )
    title_style = ParagraphStyle(
        "NexoraTitle",
        parent=body,
        fontSize=20,
        leading=24,
        spaceAfter=8,
        textColor=colors.HexColor("#111827"),
    )
    heading = ParagraphStyle(
        "NexoraHeading",
        parent=body,
        fontSize=13,
        leading=16,
        spaceBefore=8,
        spaceAfter=5,
        textColor=colors.HexColor("#2E74B5"),
    )
    table_body = ParagraphStyle(
        "NexoraTableBody",
        parent=body,
        fontSize=8.5,
        leading=10.5,
        spaceAfter=0,
    )
    table_header = ParagraphStyle(
        "NexoraTableHeader",
        parent=table_body,
        textColor=colors.white,
    )
    footer = ParagraphStyle("NexoraFooter", parent=body, fontSize=7.5, alignment=TA_RIGHT, textColor=colors.HexColor("#6B7280"))
    story = [
        Paragraph("NEXORA · РЕЗУЛЬТАТ ЗАДАЧИ", ParagraphStyle("Kicker", parent=body, fontSize=8.5, textColor=colors.HexColor("#2E74B5"))),
        Paragraph(escape(str(task["title"])), title_style),
        Table(
            [
                ["Task ID", str(task["task_id"])],
                ["Status", "COMPLETED"],
                ["Completed", str(task.get("completed_at") or "—")[:32]],
            ],
            colWidths=[1.55 * inch, 5.51 * inch],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F4F7")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        Spacer(1, 8),
        Paragraph("Результат", heading),
    ]
    index = 0
    while index < len(content.blocks):
        block = content.blocks[index]
        if block.kind in {"table_header", "table_row"}:
            rows = [block]
            column_count = len(block.cells)
            index += 1
            while (
                index < len(content.blocks)
                and content.blocks[index].kind in {"table_header", "table_row"}
                and len(content.blocks[index].cells) == column_count
            ):
                rows.append(content.blocks[index])
                index += 1
            table_data = []
            for row in rows:
                style = table_header if row.kind == "table_header" else table_body
                table_data.append(
                    [Paragraph(escape(value), style) for value in row.cells]
                )
            widths = (
                [1.6 * inch, 5.46 * inch]
                if column_count == 2
                else [7.06 * inch / column_count] * column_count
            )
            table_style = [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            repeat_rows = 0
            if rows[0].kind == "table_header":
                table_style.extend(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ]
                )
                repeat_rows = 1
            story.append(
                Table(
                    table_data,
                    colWidths=widths,
                    repeatRows=repeat_rows,
                    style=TableStyle(table_style),
                )
            )
            story.append(Spacer(1, 5))
            continue
        if block.kind == "heading":
            story.append(Paragraph(escape(block.text), heading))
        elif block.kind == "bullet":
            story.append(Paragraph(escape(block.text), body, bulletText="•"))
        elif block.kind == "numbered":
            story.append(Paragraph(escape(block.text), body, bulletText=f"{block.label}."))
        elif block.kind == "key_value":
            story.append(
                Paragraph(
                    f"<b>{escape(block.label)}:</b> {escape(block.text)}",
                    body,
                )
            )
        else:
            story.append(Paragraph(escape(block.text), body))
        index += 1
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"{escape(str(task['task_id']))} · Generated by Nexora", footer))
    document.build(story)
    payload = output.getvalue()
    if not payload.startswith(b"%PDF-") or b"/JavaScript" in payload or b"/Launch" in payload:
        raise DocumentRenderError("generated PDF failed safety validation")
    return payload


def render_xlsx(task: dict[str, Any]) -> bytes:
    """Create a safe three-sheet workbook with useful structured content."""

    content = parse_artifact_content(str(task["result"]))
    summary_rows: list[tuple[Any, ...]] = [
        ("NEXORA TASK RESULT", ""),
        ("Task ID", str(task["task_id"])),
        ("Название", str(task["title"])),
        ("Статус", "COMPLETED"),
        ("Завершена", str(task.get("completed_at") or "—")[:32]),
        ("Краткое содержание", content.summary),
        ("Количество разделов", content.section_count),
        ("Структурных элементов", len(content.data_rows)),
        ("Рекомендаций", len(content.recommendation_rows)),
    ]
    data_rows: list[tuple[Any, ...]] = [
        ("Раздел", "Тип", "Элемент", "Подробности"),
        *content.data_rows,
    ]
    recommendation_rows: list[tuple[Any, ...]] = [
        ("Раздел", "Рекомендация", "Статус"),
        *content.recommendation_rows,
    ]

    def column_name(index: int) -> str:
        value = ""
        current = index
        while current:
            current, remainder = divmod(current - 1, 26)
            value = chr(65 + remainder) + value
        return value

    def cell(reference: str, value: Any, style: int = 0) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{reference}" s="{style}"><v>{value}</v></c>'
        text = _clean_spreadsheet_text(value)
        return (
            f'<c r="{reference}" t="inlineStr" s="{style}">'
            f'<is><t xml:space="preserve">{escape(text)}</t></is></c>'
        )

    def worksheet(
        rows: list[tuple[Any, ...]],
        widths: tuple[float, ...],
        *,
        summary: bool = False,
    ) -> str:
        rendered_rows = []
        for row_index, row in enumerate(rows, start=1):
            line_count = max(
                (
                    max(
                        1,
                        (
                            len(str(value or ""))
                            + max(12, int(widths[column_index] * 1.05))
                            - 1
                        )
                        // max(12, int(widths[column_index] * 1.05)),
                    )
                    for column_index, value in enumerate(row)
                    if column_index < len(widths)
                ),
                default=1,
            )
            height = 30 if row_index == 1 else min(120, 12 + 18 * line_count)
            cells = []
            for column_index, value in enumerate(row, start=1):
                if summary:
                    style = 1 if row_index == 1 else 3 if column_index == 1 else 4
                else:
                    style = 2 if row_index == 1 else 4
                cells.append(cell(f"{column_name(column_index)}{row_index}", value, style))
            rendered_rows.append(
                f'<row r="{row_index}" ht="{height}" customHeight="1">{"".join(cells)}</row>'
            )
        columns = "".join(
            f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
            for index, width in enumerate(widths, start=1)
        )
        last_column = column_name(len(widths))
        auto_filter = (
            ""
            if summary
            else f'<autoFilter ref="A1:{last_column}{max(1, len(rows))}"/>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0" showGridLines="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews>'
            f"<cols>{columns}</cols>"
            f'<sheetData>{"".join(rendered_rows)}</sheetData>'
            f"{auto_filter}</worksheet>"
        )

    sheets = {
        "xl/worksheets/sheet1.xml": worksheet(summary_rows, (25, 86), summary=True),
        "xl/worksheets/sheet2.xml": worksheet(data_rows, (24, 16, 44, 70)),
        "xl/worksheets/sheet3.xml": worksheet(recommendation_rows, (26, 84, 16)),
    }
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<bookViews><workbookView activeTab="0"/></bookViews><sheets>'
            '<sheet name="Сводка" sheetId="1" r:id="rId1"/>'
            '<sheet name="Данные" sheetId="2" r:id="rId2"/>'
            '<sheet name="Рекомендации" sheetId="3" r:id="rId3"/>'
            '</sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>'
            '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="3"><font><sz val="11"/><name val="Aptos"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos Display"/></font>'
            '<font><b/><color rgb="FF1F2937"/><sz val="11"/><name val="Aptos"/></font></fonts>'
            '<fills count="4"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FFF2F4F7"/><bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
            '<border><left style="thin"><color rgb="FFD1D5DB"/></left><right style="thin"><color rgb="FFD1D5DB"/></right>'
            '<top style="thin"><color rgb="FFD1D5DB"/></top><bottom style="thin"><color rgb="FFD1D5DB"/></bottom><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
            '<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
        ),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(str(task["title"]))}</dc:title><dc:creator>Nexora</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{datetime.now(timezone.utc).isoformat()}</dcterms:created>'
            '</cp:coreProperties>'
        ),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>Nexora</Application></Properties>'
        ),
        **sheets,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as workbook:
        for name, file_content in files.items():
            workbook.writestr(name, file_content.encode("utf-8"))
    payload = output.getvalue()
    _verify_ooxml(payload, "xl/")
    with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        if not all(name in workbook_xml for name in ("Сводка", "Данные", "Рекомендации")):
            raise DocumentRenderError("generated spreadsheet is missing required worksheets")
        data_xml = workbook.read("xl/worksheets/sheet2.xml").decode("utf-8")
        if str(task["task_id"]) not in workbook.read("xl/worksheets/sheet1.xml").decode("utf-8"):
            raise DocumentRenderError("generated spreadsheet is missing task metadata")
        if not content.data_rows or escape(content.data_rows[0][2]) not in data_xml:
            raise DocumentRenderError("generated spreadsheet is missing structured task data")
    return payload


def render_zip(task: dict[str, Any], members: dict[str, bytes]) -> bytes:
    """Bundle already-rendered safe artifacts with a checksum manifest."""

    safe_members = {
        name: bytes(payload)
        for name, payload in members.items()
        if re.fullmatch(r"result\.(?:md|json|docx|xlsx|pdf)", name)
    }
    safe_members["README.txt"] = (
        "Nexora task artifact package\n"
        f"Task ID: {_clean_spreadsheet_text(task['task_id'])}\n"
        f"Title: {_clean_spreadsheet_text(task['title'])}\n"
        "Contents: Markdown source, JSON result, DOCX report, PDF report, and XLSX structured data.\n"
        "Integrity: verify every file against MANIFEST.json before use.\n"
        "Security: this package contains no executable files, macros, or external links.\n"
    ).encode("utf-8")
    manifest = {
        "task_id": str(task["task_id"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"name": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
            for name, payload in sorted(safe_members.items())
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(safe_members.items()):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
        info = zipfile.ZipInfo("MANIFEST.json")
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        archive.writestr(info, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    payload = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in archive.namelist()):
            raise DocumentRenderError("generated archive failed path validation")
    return payload


def _verify_ooxml(payload: bytes, required_prefix: str) -> None:
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise DocumentRenderError("generated Office document is not a valid package")
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        names = package.namelist()
        if not any(name.startswith(required_prefix) for name in names):
            raise DocumentRenderError("generated Office document is incomplete")
        if any(name.casefold().endswith(("vbaproject.bin", ".exe", ".dll", ".js", ".ps1", ".sh")) for name in names):
            raise DocumentRenderError("generated Office document contains executable content")
        for name in names:
            if name.endswith(".rels"):
                content = package.read(name).decode("utf-8", errors="ignore").casefold()
                if 'targetmode="external"' in content:
                    raise DocumentRenderError("external Office relationships are not allowed")


def render_rich_artifacts(task: dict[str, Any], base_members: dict[str, bytes]) -> dict[str, bytes]:
    """Render the selected safe rich formats for one completed task."""

    rendered: dict[str, bytes] = {}
    formats = selected_formats(str(task["title"]), str(task["result"]))
    if "docx" in formats:
        rendered["docx"] = render_docx(task)
    if "pdf" in formats:
        rendered["pdf"] = render_pdf(task)
    if "xlsx" in formats:
        rendered["xlsx"] = render_xlsx(task)
    if "zip" in formats:
        members = {f"result.{kind if kind != 'markdown' else 'md'}": value for kind, value in {**base_members, **rendered}.items()}
        rendered["zip"] = render_zip(task, members)
    return rendered
