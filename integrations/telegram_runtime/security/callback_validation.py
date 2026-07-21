from __future__ import annotations

import re


CALLBACK_PATTERN = re.compile(r"^apr:(approve|reject):(APR-[A-Z0-9]{8})$")


def parse_approval_callback(value: str) -> tuple[str, str] | None:
    match = CALLBACK_PATTERN.fullmatch(value)
    if match is None:
        return None
    return match.group(1), match.group(2)
