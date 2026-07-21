# Nexora v2.3.0

Nexora 2.3 is the Cloud & Billing Foundation release. It adds plans,
subscriptions, trusted usage metering, quotas, tenant billing views, an
approval-gated admin console, and metadata-only cloud provisioning.

Migration 007 is additive and reversible. Before applying it, SQLite creates a
mode-600 `pre-v7` backup and checks integrity. Rolling back 007 removes only the
new cloud/billing tables and preserves all v2.2 tenant data.

This release does not connect real payments, modify production, restart or
publish OpenClaw Gateway, or allocate external cloud infrastructure.
