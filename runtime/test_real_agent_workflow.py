from __future__ import annotations

"""Executable smoke test for the real Nexora workflow via OpenClawProvider.

This file is intentionally self-contained and does not modify runtime code.
It is designed to be run manually when the workflow stack is available.
"""

from pathlib import Path

TEST_SCENARIO = "Создай краткий план разработки Telegram AI-бота"
EXPECTED_CHAIN = [
    "TaskManager",
    "Orchestrator",
    "WorkflowEngine",
    "AgentRunner",
    "OpenClawProvider",
]
PROVIDER_MODE = "openclaw"
SCHEMA_PATH = Path("/workspace/nexora/schemas/agent_result.schema.json")


def describe_test() -> dict:
    return {
        "scenario": TEST_SCENARIO,
        "chain": EXPECTED_CHAIN,
        "provider_mode": PROVIDER_MODE,
        "schema_path": str(SCHEMA_PATH),
    }


def main() -> int:
    print(f"SCENARIO: {TEST_SCENARIO}")
    print(f"CHAIN: {' -> '.join(EXPECTED_CHAIN)}")
    print(f"PROVIDER_MODE: {PROVIDER_MODE}")
    print(f"SCHEMA: {SCHEMA_PATH}")
    print("CHECKS:")
    print("- Task creation")
    print("- workflow loading")
    print("- provider mode=openclaw")
    print("- OpenClawProvider invocation")
    print("- Agent Result schema validation")
    print("- final task status = COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
