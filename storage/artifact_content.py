"""Deterministic, side-effect-free parsing for rich task artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


MAX_BLOCKS = 250
MAX_BLOCK_TEXT = 4000
DEFAULT_SECTION = "Обзор"
RECOMMENDATION_MARKERS = (
    "рекоменд",
    "следующ",
    "дальше",
    "план",
    "действ",
    "recommend",
    "next",
    "action",
    "roadmap",
)


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    section: str
    text: str = ""
    level: int = 0
    label: str = ""
    cells: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactContent:
    blocks: tuple[ContentBlock, ...]
    summary: str
    data_rows: tuple[tuple[str, str, str, str], ...]
    recommendation_rows: tuple[tuple[str, str, str], ...]
    section_count: int


def _clean(value: str, limit: int = MAX_BLOCK_TEXT) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<!\\)[*_`]{1,3}", "", text)
    return text[:limit]


def _logical_lines(result: str) -> list[str]:
    text = str(result or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<!\n)\s+(?=#{1,3}\s+\S)", "\n", text)
    text = re.sub(
        r"(?m)^(#{1,3}\s+[^#\n|]{1,120}?)\s+(?=[-*•]\s+\S|\d+[.)]\s+\S|\|)",
        r"\1\n",
        text,
    )
    text = re.sub(r"(?<=[.:;])\s+(?=[-*•]\s+\S)", "\n", text)
    text = re.sub(r"(?<=[.:;])\s+(?=\d+[.)]\s+\S)", "\n", text)
    return [line.strip() for line in text.split("\n") if line.strip()]


def _table_cells(line: str) -> tuple[str, ...]:
    if not (line.startswith("|") and line.endswith("|")):
        return ()
    cells = tuple(_clean(value, 1000) for value in line.strip("|").split("|"))
    return cells if 2 <= len(cells) <= 12 and all(cells) else ()


def _is_table_separator(cells: Iterable[str]) -> bool:
    values = tuple(cells)
    return bool(values) and all(re.fullmatch(r":?-{3,}:?", value.replace(" ", "")) for value in values)


def parse_artifact_content(result: str) -> ArtifactContent:
    """Parse Markdown-like model text into safe presentation blocks."""

    blocks: list[ContentBlock] = []
    section = DEFAULT_SECTION
    table_header_pending = False
    for raw in _logical_lines(result):
        if len(blocks) >= MAX_BLOCKS:
            break
        heading = re.match(r"^(#{1,3})\s+(.+)$", raw)
        if heading:
            level = len(heading.group(1))
            section = _clean(heading.group(2), 200) or DEFAULT_SECTION
            blocks.append(ContentBlock("heading", section, section, level=level))
            table_header_pending = False
            continue

        cells = _table_cells(raw)
        if cells:
            if _is_table_separator(cells):
                if blocks and blocks[-1].kind == "table_row":
                    previous = blocks[-1]
                    blocks[-1] = ContentBlock(
                        "table_header",
                        previous.section,
                        cells=previous.cells,
                    )
                table_header_pending = False
                continue
            kind = "table_header" if table_header_pending else "table_row"
            blocks.append(ContentBlock(kind, section, cells=cells))
            table_header_pending = kind == "table_row" and len(blocks) == 1
            continue

        bullet = re.match(r"^[-*•]\s+(.+)$", raw)
        if bullet:
            blocks.append(ContentBlock("bullet", section, _clean(bullet.group(1))))
            table_header_pending = False
            continue

        numbered = re.match(r"^(\d+)[.)]\s+(.+)$", raw)
        if numbered:
            blocks.append(
                ContentBlock(
                    "numbered",
                    section,
                    _clean(numbered.group(2)),
                    label=numbered.group(1),
                )
            )
            table_header_pending = False
            continue

        key_value = re.match(r"^([^:]{1,80}):\s+(.+)$", raw)
        if key_value:
            blocks.append(
                ContentBlock(
                    "key_value",
                    section,
                    _clean(key_value.group(2)),
                    label=_clean(key_value.group(1), 80),
                )
            )
            table_header_pending = False
            continue

        paragraph = _clean(raw)
        if paragraph:
            blocks.append(ContentBlock("paragraph", section, paragraph))
        table_header_pending = False

    if not blocks:
        blocks = [ContentBlock("paragraph", DEFAULT_SECTION, "Результат не содержит отображаемого текста.")]

    data_rows: list[tuple[str, str, str, str]] = []
    recommendations: list[tuple[str, str, str]] = []
    summary = ""
    section_names: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            if block.section not in section_names:
                section_names.append(block.section)
            continue
        if not summary and block.text:
            summary = block.text[:500]
        if block.kind in {"table_header", "table_row"}:
            item = block.cells[0]
            details = " | ".join(block.cells[1:])
            block_type = "Table header" if block.kind == "table_header" else "Table row"
        elif block.kind == "key_value":
            item, details, block_type = block.label, block.text, "Field"
        else:
            item = block.text[:180]
            details = block.text if len(block.text) > 180 else ""
            block_type = {
                "bullet": "Bullet",
                "numbered": "Step",
                "paragraph": "Paragraph",
            }.get(block.kind, "Content")
        if item:
            data_rows.append((block.section, block_type, item, details))
        if (
            item
            and block.kind in {"bullet", "numbered", "table_row"}
            and any(marker in block.section.casefold() for marker in RECOMMENDATION_MARKERS)
        ):
            recommendations.append((block.section, item, "Review"))

    if not summary:
        summary = _clean(result, 500) or "Результат сформирован."
    if not recommendations:
        candidates = [
            row
            for block, row in zip(
                (value for value in blocks if value.kind != "heading"),
                data_rows,
            )
            if block.kind in {"bullet", "numbered"}
        ]
        recommendations = [
            (section_name, item, "Review")
            for section_name, _, item, _ in candidates[-10:]
        ]
    if not recommendations:
        recommendations = [(DEFAULT_SECTION, summary[:500], "Review")]

    return ArtifactContent(
        blocks=tuple(blocks),
        summary=summary,
        data_rows=tuple(data_rows[:MAX_BLOCKS]),
        recommendation_rows=tuple(recommendations[:50]),
        section_count=max(1, len(section_names)),
    )
