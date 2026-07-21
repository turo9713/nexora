from __future__ import annotations

from typing import Any


NEW_TASK_BUTTON = "🧠 Новая задача"
STATUS_BUTTON = "📊 Статус"
HISTORY_BUTTON = "📋 История"
CANCEL_BUTTON = "🛑 Отменить"
RESET_BUTTON = "🧹 Сбросить контекст"

BUTTON_TO_COMMAND = {
    NEW_TASK_BUTTON: "/newtask",
    STATUS_BUTTON: "/status",
    HISTORY_BUTTON: "/history",
    CANCEL_BUTTON: "/cancel",
    RESET_BUTTON: "/reset",
}


def main_reply_markup() -> dict[str, Any]:
    return {
        "keyboard": [
            [{"text": NEW_TASK_BUTTON}, {"text": STATUS_BUTTON}],
            [{"text": HISTORY_BUTTON}, {"text": CANCEL_BUTTON}],
            [{"text": RESET_BUTTON}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "selective": True,
        "input_field_placeholder": "Выберите действие Nexora",
    }
