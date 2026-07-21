# Contributing to Nexora

1. Branch from a clean release tag and keep commits focused.
2. Never commit credentials, identifiers, runtime state, user content, logs,
   databases, private integrations, commercial skills, or VPS configuration.
3. Preserve public runtime APIs and deny-by-default policy behavior.
4. Do not add executable skill/plugin code or network access without a security
   design and tests.
5. Add unit, integration, security, and migration tests for changed behavior.
6. Run `python -m pytest -q`, `bash scripts/secret-scan.sh`, and the release
   Compose validation before requesting review.
7. Document security effects, compatibility, migration, and rollback.

Use Semantic Versioning. Changes that alter security boundaries require an
explicit maintainer review. A pull request must not weaken authentication,
owner isolation, approval checks, redaction, or container hardening.
