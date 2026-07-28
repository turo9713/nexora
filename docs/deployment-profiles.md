# Deployment Profiles

Migration 012 installs metadata-only profiles for Development, Staging,
Production, and Enterprise. Profiles describe resources, limits, security
settings, and enabled platform capabilities. They do not deploy containers,
change Compose, restart services, or grant permissions.

All profiles preserve deny-by-default policies, sandboxing, and approvals.
