from __future__ import annotations

import re
from typing import Any, Callable


class GitHubIntegrationError(PermissionError):
    pass


REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


class GitHubIntegration:
    """Read-only GitHub API adapter; write, push, merge, and mutation are absent."""

    api_base = "https://api.github.com"

    def repository_plan(self, repository: str, *, include_pull_requests: bool = True) -> dict[str, Any]:
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("invalid repository")
        endpoints = [f"/repos/{repository}", f"/repos/{repository}/contents/"]
        if include_pull_requests:
            endpoints.append(f"/repos/{repository}/pulls?state=open")
        return {"repository": repository, "mode": "READ_ONLY", "endpoints": endpoints, "writes": False}

    def request(self, method: str, path: str, transport: Callable[[str, str], Any]) -> Any:
        if method.upper() != "GET":
            raise GitHubIntegrationError("github write operation denied")
        if not path.startswith("/repos/") or ".." in path or "//" in path:
            raise GitHubIntegrationError("github path denied")
        return transport("GET", self.api_base + path)
