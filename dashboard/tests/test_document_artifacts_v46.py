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
        "result": "## Итог\n- Таблица подготовлена\n- Архив сформирован\nСумма: 125 000 ₽",
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
        assert not any(name.startswith("xl/externalLinks/") for name in names)
        assert not any(name.casefold().endswith(("vbaproject.bin", ".exe", ".dll")) for name in names)
        sheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "<f" not in sheet
        assert "NX-DOC-001" in sheet
        assert "Таблица подготовлена" in sheet


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
            "result.md",
            "result.json",
            "result.docx",
            "result.pdf",
            "result.xlsx",
        }
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["task_id"] == "NX-DOC-001"
        assert len(manifest["files"]) == 5
        assert all(".." not in Path(name).parts for name in names)


def test_binary_preview_is_safe_and_telegram_delivers_all_rich_formats() -> None:
    project = Path(__file__).resolve().parents[2]
    handler_source = (project / "integrations" / "telegram_runtime" / "handlers.py").read_text(encoding="utf-8")
    artifact_source = (project / "storage" / "artifacts.py").read_text(encoding="utf-8")
    assert '("docx", "xlsx", "pdf", "zip")' in handler_source
    assert "Предпросмотр бинарного файла недоступен" in artifact_source
