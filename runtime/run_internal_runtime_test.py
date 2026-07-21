"""Workspace-only runner for the internal runtime smoke test."""

from __future__ import annotations

from .test_internal_runtime import run_test


def main() -> None:
    result = run_test()
    print(result)


if __name__ == "__main__":
    main()
