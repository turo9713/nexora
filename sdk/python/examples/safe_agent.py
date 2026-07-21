"""Safe SDK example: declaration and planning only; no code execution."""

MANIFEST = {
    "id": "example-writer", "name": "Example Writer", "version": "1.0.0",
    "description": "Creates workspace-only drafts", "goal": "Create reviewed drafts",
    "role": "content", "skills": ["content-writer"], "knowledge": ["workspace-style"],
    "tools": ["text_generation"], "permissions": ["drafts:write"],
    "memory_scope": "AGENT", "approval_rules": ["publish"],
}
