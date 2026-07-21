from __future__ import annotations

from ..keyboards import main_reply_markup


def menu_response() -> tuple[str, dict]:
    return "Главное меню Nexora", main_reply_markup()
