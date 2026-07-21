# Creator Guide

Nexora 2.5 provides an owner-isolated creator control plane. Create a profile in
the authenticated `/creator` Dashboard, prepare a metadata-only package draft,
submit it, validate it, and publish it only after creator verification.

The lifecycle is `DRAFT -> SUBMITTED -> VALIDATING -> APPROVED -> PUBLISHED`.
Published manifests and checksums are immutable. Archive and rollback are
approval-protected. Packages never contain or execute arbitrary code.

Public profiles expose a display name, bio, avatar reference, package count,
installs, rating, and verification badge. Owner identifiers and tenant details
are never returned.
