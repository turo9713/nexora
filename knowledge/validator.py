from __future__ import annotations

import re


class KnowledgeValidationError(ValueError):
    pass


SENSITIVE = (
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|nx_live)_[A-Za-z0-9_-]{20,}\b", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|api[_-]?key|token|authorization)\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://\S+"),
)


def validate_document(name: str, document_type: str, content: str, access_level: str) -> tuple[str, str, str, str]:
    clean_name = " ".join(str(name).split())[:160]
    clean_type = str(document_type).strip().lower()[:40]
    clean_content = str(content).replace("\x00", "").strip()
    level = str(access_level).upper()
    if not clean_name or not re.fullmatch(r"[a-z0-9_-]{2,40}", clean_type) or not clean_content or len(clean_content) > 100_000:
        raise KnowledgeValidationError("invalid knowledge document")
    if level not in {"TEAM", "MANAGERS", "ADMINS"}:
        raise KnowledgeValidationError("invalid knowledge access")
    if any(pattern.search(clean_content) for pattern in SENSITIVE):
        raise KnowledgeValidationError("sensitive content denied")
    return clean_name, clean_type, clean_content, level
