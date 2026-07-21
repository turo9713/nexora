from __future__ import annotations

from typing import Any


def approval_keyboard(approval_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Подтвердить", "callback_data": f"apr:approve:{approval_id}"},
                {"text": "❌ Отклонить", "callback_data": f"apr:reject:{approval_id}"},
            ]
        ]
    }


def approval_decision_message(status: str) -> str:
    messages = {
        "APPROVED": "✅ Действие подтверждено.\nВыполнение продолжено.",
        "REJECTED": "❌ Действие отклонено.\nЗадача остановлена.",
        "EXPIRED": "Подтверждение истекло. Запусти действие повторно.",
        "ALREADY_USED": "Подтверждение уже использовано. Повторное выполнение заблокировано.",
        "NOT_FOUND": "Подтверждение не найдено или недоступно.",
        "INVALID": "Некорректное подтверждение.",
    }
    return messages.get(status, "Подтверждение не обработано.")
