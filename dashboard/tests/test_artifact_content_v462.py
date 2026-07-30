from __future__ import annotations

from nexora.storage.artifact_content import parse_artifact_content, structured_table_blocks


def test_inline_markdown_is_split_into_structured_sections_and_rows() -> None:
    result = (
        "Краткое введение. "
        "## Возможности "
        "- Безопасная оркестрация; "
        "- Изолированные рабочие пространства. "
        "## Сравнение "
        "| Компонент | Назначение | Статус |\n"
        "|---|---|---|\n"
        "| Runtime | Выполнение задач | Готово |\n"
        "## Рекомендации "
        "1. Подключить дополнительные проверки."
    )
    content = parse_artifact_content(result)

    assert content.section_count == 3
    assert any(block.kind == "table_header" for block in content.blocks)
    assert any(
        block.kind == "table_row" and block.cells[0] == "Runtime"
        for block in content.blocks
    )
    assert any(row[0] == "Возможности" and row[1] == "Bullet" for row in content.data_rows)
    assert content.recommendation_rows[0][0] == "Рекомендации"
    assert "Подключить дополнительные проверки" in content.recommendation_rows[0][1]


def test_content_parser_is_bounded_and_has_safe_fallback() -> None:
    content = parse_artifact_content("\x00")
    assert content.summary
    assert content.data_rows
    assert content.recommendation_rows

    many = parse_artifact_content("\n".join(f"- item {index}" for index in range(1000)))
    assert len(many.blocks) <= 250
    assert len(many.data_rows) <= 250


def test_structured_table_fallback_uses_parsed_rows() -> None:
    content = parse_artifact_content("## Сравнение\n- Runtime — готов\n- Telegram — готов")
    rows = structured_table_blocks(content)

    assert rows[0].kind == "table_header"
    assert rows[0].cells == ("Раздел", "Тип", "Элемент", "Подробности")
    assert len(rows) == 3
    assert rows[1].cells[0] == "Сравнение"
