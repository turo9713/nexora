# Creator Verification

Levels are `NEW_CREATOR`, `VERIFIED_CREATOR`, and `TRUSTED_CREATOR`. Grant,
revoke, suspension, and blocking require the protected administrator namespace,
an exact one-time approval, Policy Engine authorization, and audit logging.

Trusted status additionally requires at least three published packages, no
failed release, at least 95% measured reliability, and acceptable review
quality. Verification never grants shell, secret, Docker, production, or
payment access.
