# Cloud architecture foundation

The v2.3 Cloud Manager prepares a safe tenant lifecycle:

```text
Approved admin request
  -> create customer organization
  -> assign reviewed plan
  -> create isolated workspace
  -> record local resource metadata
  -> READY
```

Provisioning requires the protected admin namespace, an exact one-time
`cloud:tenant_provision` approval, and Policy Engine authorization. The manager
does not call cloud vendors, create servers, change DNS, open ports, access
Docker, expose OpenClaw Gateway, or process payments. `cloud_resources` records
only local allocation metadata so a future provider adapter can be designed and
approved separately.

Tenant isolation remains `User -> Organization -> Workspace -> RBAC -> Policy ->
Resource`. Subscription and usage lookups add organization-qualified queries;
they never weaken workspace checks.
