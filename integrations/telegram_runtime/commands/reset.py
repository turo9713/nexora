from __future__ import annotations


def reset_response(context) -> str:
    context.clear()
    return "Контекст диалога очищен. Для новой задачи используй /newtask <описание>."
