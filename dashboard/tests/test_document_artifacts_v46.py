from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from nexora.storage.document_artifacts import (
    render_docx,
    render_pdf,
    render_rich_artifacts,
    render_xlsx,
    required_artifact_formats,
    selected_formats,
)


def sample_task() -> dict[str, str]:
    return {
        "task_id": "NX-DOC-001",
        "title": "Создай Excel-таблицу и ZIP-архив отчёта",
        "result": (
            "## Итог\n"
            "- Таблица подготовлена\n"
            "- Архив сформирован\n"
            "## Данные\n"
            "| Компонент | Статус | Описание |\n"
            "|---|---|---|\n"
            "| Runtime | Готово | Выполнение задач |\n"
            "## Рекомендации\n"
            "1. Проверить результат перед публикацией.\n"
            "Сумма: 125 000 ₽"
        ),
        "completed_at": "2026-07-30T12:00:00+00:00",
    }


def test_format_selection_is_deterministic_and_has_safe_defaults() -> None:
    assert selected_formats("Обычная задача", "Готово") == ("docx", "pdf")
    assert selected_formats("Excel-таблица и ZIP-архив", "Готово") == ("docx", "pdf", "xlsx", "zip")
    assert required_artifact_formats("Excel ZIP", "Done") == (
        "markdown",
        "json",
        "docx",
        "pdf",
        "xlsx",
        "zip",
    )


def test_docx_is_macro_free_without_external_relationships() -> None:
    payload = render_docx(sample_task())
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        names = package.namelist()
        assert "word/document.xml" in names
        assert not any(name.casefold().endswith(("vbaproject.bin", ".exe", ".dll")) for name in names)
        relationships = b"".join(package.read(name) for name in names if name.endswith(".rels"))
        assert b'TargetMode="External"' not in relationships
        document = package.read("word/document.xml").decode("utf-8")
        assert "NX-DOC-001" in document
        assert "Таблица подготовлена" in document
        assert "Runtime" in document
        assert document.count("<w:tbl>") >= 2


def test_docx_builds_structured_table_for_excel_intent_without_markdown_table() -> None:
    task = sample_task()
    task["result"] = "## Сравнение\n- Runtime готов\n- Telegram готов"
    payload = render_docx(task)
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        document = package.read("word/document.xml").decode("utf-8")
        assert document.count("<w:tbl>") >= 2
        assert "Структурированные данные" in document


def test_pdf_embeds_cyrillic_font_and_has_no_active_actions() -> None:
    payload = render_pdf(sample_task())
    assert payload.startswith(b"%PDF-")
    assert b"/JavaScript" not in payload
    assert b"/Launch" not in payload
    assert b"DejaVu" in payload


def test_xlsx_is_formula_macro_and_external_link_free() -> None:
    payload = render_xlsx(sample_task())
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        names = package.namelist()
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "xl/worksheets/sheet3.xml" in names
        assert not any(name.startswith("xl/externalLinks/") for name in names)
        assert not any(name.casefold().endswith(("vbaproject.bin", ".exe", ".dll")) for name in names)
        workbook = package.read("xl/workbook.xml").decode("utf-8")
        assert all(name in workbook for name in ("Сводка", "Данные", "Рекомендации"))
        sheets = [
            package.read(f"xl/worksheets/sheet{index}.xml").decode("utf-8")
            for index in (1, 2, 3)
        ]
        assert all("<f" not in sheet for sheet in sheets)
        assert "NX-DOC-001" in sheets[0]
        assert "Таблица подготовлена" in sheets[1]
        assert "Runtime" in sheets[1]
        assert "Проверить результат" in sheets[2]


def test_zip_contains_only_allowlisted_files_and_checksum_manifest() -> None:
    base = {
        "markdown": b"# Safe\n",
        "json": json.dumps({"status": "COMPLETED"}).encode(),
    }
    rendered = render_rich_artifacts(sample_task(), base)
    assert set(rendered) == {"docx", "pdf", "xlsx", "zip"}
    with zipfile.ZipFile(io.BytesIO(rendered["zip"])) as archive:
        names = set(archive.namelist())
        assert names == {
            "MANIFEST.json",
            "README.txt",
            "result.md",
            "result.json",
            "result.docx",
            "result.pdf",
            "result.xlsx",
        }
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["task_id"] == "NX-DOC-001"
        assert len(manifest["files"]) == 6
        assert b"Nexora task artifact package" in archive.read("README.txt")
        assert all(".." not in Path(name).parts for name in names)


def test_binary_preview_is_safe_and_telegram_delivers_all_rich_formats() -> None:
    project = Path(__file__).resolve().parents[2]
    handler_source = (project / "integrations" / "telegram_runtime" / "handlers.py").read_text(encoding="utf-8")
    artifact_source = (project / "storage" / "artifacts.py").read_text(encoding="utf-8")
    assert '("docx", "xlsx", "pdf", "zip")' in handler_source
    assert "Предпросмотр бинарного файла недоступен" in artifact_source
