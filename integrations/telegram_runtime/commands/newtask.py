from __future__ import annotations

from dataclasses import dataclass


FORBIDDEN_MARKERS = (
    "rm -rf",
    "приватный ключ",
    "private key",
    "отключи firewall",
    "disable firewall",
    "измени ssh",
    "change ssh",
    "форматируй диск",
    "format disk",
    "торговая операция",
    "реальная торговля",
    "переведи деньги",
    "массовая рассылка",
    "извлеки секрет",
    "покажи токен",
)


@dataclass(frozen=True)
class ApprovalRequirement:
    action_type: str
    summary: str
    risk: str


APPROVAL_RULES = (
    (("перезапуст", "restart"), "service_restart", "Перезапуск сервиса", "Сервис может быть временно недоступен."),
    (("docker", "контейнер"), "docker_change", "Изменение Docker-контейнера", "Изменение может повлиять на работающие сервисы."),
    (("git push", " merge", "deployment", "деплой"), "deployment", "Публикация изменений", "Изменения могут попасть в production."),
    (("удали файл", "delete file", "удалить файл"), "file_delete", "Удаление файлов", "Удалённые данные могут быть невосстановимы."),
    (("публику", "publish"), "publication", "Публикация контента", "Контент станет доступен внешним пользователям."),
    (("базу данных", "database", "миграци"), "database_change", "Изменение базы данных", "Операция может необратимо изменить данные."),
    (("отправь сообщение", "send message"), "external_message", "Отправка внешнего сообщения", "Сообщение будет передано третьей стороне."),
)


def normalize_description(value: str, limit: int = 2000) -> str:
    return " ".join(value.replace("\x00", "").split())[:limit]


def is_forbidden(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in FORBIDDEN_MARKERS)


def approval_requirement(value: str) -> ApprovalRequirement | None:
    lowered = value.casefold()
    for markers, action_type, summary, risk in APPROVAL_RULES:
        if any(marker in lowered for marker in markers):
            return ApprovalRequirement(action_type, summary, risk)
    return None
