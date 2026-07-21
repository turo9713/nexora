# Integrations

## GitHub

`github-integration` and the `github-agent` skill are read-only foundations.
Only `GET` routes under `https://api.github.com/repos/` are accepted. Push,
merge, mutation, shell, arbitrary hosts, and production writes are absent and
denied. No GitHub credential is provisioned in v1.8.

## Content platform

The content route is `Research -> Content -> QA -> Approval -> Publish`.
Nexora v1.8 prepares drafts and publication metadata only. Publication without
an approval raises a hard denial; even after approval, no external publisher is
configured, so no content is automatically posted.
