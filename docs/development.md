# Development and diagnostics

Use only the local runtime virtual environment:

```bash
cd /workspace
/workspace/nexora/runtime/.venv/bin/python -m pytest -q \
  nexora/integrations/telegram_runtime/tests nexora/tests nexora/dashboard/tests

/workspace/nexora/runtime/.venv/bin/python -m pytest -q \
  nexora/tests/test_skills.py nexora/dashboard/tests

/workspace/nexora/runtime/.venv/bin/python -m pytest -q \
  nexora/tests/test_public_api.py nexora/tests/test_integrations_v18.py
```

Database diagnostics:

```bash
/workspace/nexora/runtime/.venv/bin/python -m nexora.storage.migrations.import_v14 \
  --state /workspace/nexora/runtime/state/telegram_v14 \
  --database /workspace/nexora/runtime/state/database/nexora.sqlite3 --dry-run
```

Git security check:

```bash
bash /workspace/nexora/scripts/secret-scan.sh
git status --short
```

Production service checks are run through Docker by an administrator. Do not
start `bot.py` manually while `nexora-telegram` is polling.
