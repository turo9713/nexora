# Skill development

1. Copy an existing manifest inside `skills/manifests/`.
2. Use a lowercase kebab-case ID and semantic version.
3. Select only enumerated tools and the smallest filesystem/network scope.
4. Keep `shell.enabled` and `production.enabled` false and sandbox true.
5. Run validator, registry, policy, database, Dashboard, and secret-scan tests.
6. Review the Git diff and manifest hash before release.

External URLs, archives, install scripts, entrypoints, Python imports, Docker
images, environment variables, and secret references are not accepted by v1.7.
Marketplace packages must not be copied into `skills/installed/`; that directory
stores declarative receipts only and is ignored by Git except for its README.

Validation command:

```bash
cd /workspace
/workspace/nexora/runtime/.venv/bin/python -c 'from pathlib import Path; from nexora.skills.validators import SkillManifestValidator; print(SkillManifestValidator(Path("nexora/skills/manifests/skill.schema.json")).validate_file(Path("nexora/skills/manifests/content-writer.yaml"))["id"])'
```

Adding new allowlisted tools, scopes, agents, categories, or authors is a schema
and security-policy change and requires review plus a new platform release.
