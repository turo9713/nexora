from __future__ import annotations

import sys

from .passwords import hash_password


def main() -> int:
    value = sys.stdin.read(4096).rstrip("\r\n")
    try:
        encoded = hash_password(value)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
