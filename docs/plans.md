# Plans and limits

Migration 007 seeds four versioned platform plans.

| Plan | Workspaces | Members | Agents | Tasks/month | Storage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Free | 1 | 1 | 3 | 100 | 1 GiB |
| Pro | 10 | 10 | Unlimited | 5,000 | 50 GiB |
| Team | Unlimited | 100 | Unlimited | 20,000 | 200 GiB |
| Enterprise | Custom/unlimited | Custom/unlimited | Unlimited | Custom/unlimited | Custom/unlimited |

Team enables audit and knowledge-base features. Enterprise additionally marks
SSO, private deployment, and custom limits as available foundations. These are
capability declarations, not automatic infrastructure or identity-provider
configuration.

`null` represents Unlimited. Limits are evaluated against current authoritative
resource counts immediately before mutation. A denial returns `LIMIT_REACHED`
and records a safe audit/billing event. Client-supplied counters are ignored.
