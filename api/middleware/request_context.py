from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4


SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,100}$")


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    correlation_id: str


def request_context(request_id: str | None = None, correlation_id: str | None = None) -> RequestContext:
    generated = f"REQ-{uuid4().hex.upper()}"
    request = request_id if request_id and SAFE_ID.fullmatch(request_id) else generated
    correlation = correlation_id if correlation_id and SAFE_ID.fullmatch(correlation_id) else request
    return RequestContext(request[:100], correlation[:100])
