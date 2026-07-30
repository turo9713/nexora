from __future__ import annotations

from nexora.integrations.telegram_runtime.bot import TelegramBotAPI


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return b'{"ok":true,"result":{"message_id":1}}'


def test_send_document_includes_bounded_safe_caption(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(api_request, timeout):
        captured["request"] = api_request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(
        "nexora.integrations.telegram_runtime.bot.request.urlopen",
        fake_urlopen,
    )
    api = TelegramBotAPI("fixture-token")
    api.send_document(
        100,
        "NX-result.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        b"PK-safe",
        "XLSX — сводка, данные и рекомендации\nЗадача: NX-1",
    )

    body = captured["request"].data
    assert b'name="caption"' in body
    assert "XLSX — сводка, данные и рекомендации".encode("utf-8") in body
    assert b"PK-safe" in body
    assert captured["timeout"] == 40
