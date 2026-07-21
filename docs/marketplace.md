# Marketplace

Nexora Marketplace is a catalog of declarative Agent, Skill, Template, and
Integration manifests. It is not a package manager and never downloads or
executes publisher code.

Lifecycle: `DRAFT -> SUBMITTED -> VALIDATING -> APPROVED -> PUBLISHED`. A
published item can later become `DISABLED` or `REMOVED`; package versions and
events remain immutable.

Install flow: authenticated actor, workspace membership, package checksum,
manifest revalidation, Policy Engine, approval when required, installation
record, community-license metadata, audit. Low-risk metadata can be installed
directly. Medium/high-risk items and every integration require an exact,
expiring, one-time approval.

Dashboard routes are `/marketplace`, `/my-items`, and `/publisher`. Public API
scopes are `marketplace:read`, `marketplace:install`, and
`marketplace:publish`.
