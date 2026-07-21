# Webhooks

Supported events are `TASK_CREATED`, `TASK_COMPLETED`, `TASK_FAILED`,
`APPROVAL_REQUIRED`, and `SECURITY_EVENT`.

Registration accepts a plain HTTPS URL on port 443 without credentials, query,
or fragment. Activation requires the existing Policy/Approval flow. The signing
secret is derived from a protected master key, stored only as a database hash,
and shown once after approval.

Delivery headers:

- `X-Nexora-Event`;
- `X-Nexora-Request-ID`;
- `X-Nexora-Signature: sha256=<HMAC>`.

Receivers must calculate HMAC-SHA256 over the exact request body and compare in
constant time. Delivery uses a five-second timeout and up to three attempts.
Repeated failed deliveries disable the endpoint. Payload metadata is redacted
before signing. Private, loopback, reserved, and unresolved targets are denied.

No background event dispatcher is enabled in v1.8; the reviewed delivery service
is ready for a future worker, so current runtime behavior is unchanged.
