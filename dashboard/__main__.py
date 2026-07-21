from __future__ import annotations

import ssl
import sys
from urllib import request

from .backend.server import DashboardConfig, run


def healthcheck() -> int:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with request.urlopen("https://127.0.0.1:18880/healthz", timeout=5, context=context) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(healthcheck() if "--healthcheck" in sys.argv[1:] else run(DashboardConfig()))
