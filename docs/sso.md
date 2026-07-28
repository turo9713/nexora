# SSO Foundation

Nexora 3.5 defines provider-neutral readiness metadata for SAML, OIDC, and
OAuth 2.0. No external identity provider is configured or enabled, and the
production Dashboard authentication flow is unchanged.

Enabling a provider requires a separate migration plan covering issuer and
audience validation, key rotation, account linking, break-glass access, rollout,
and rollback. Provider secrets must use protected secret storage.
