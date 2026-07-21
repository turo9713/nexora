# Package format

Required manifest fields:

```yaml
id: content-optimizer
name: Content Optimizer
type: SKILL
version: 1.0.0
author: Nexora Community
description: Reviews draft structure
category: content
permissions:
  filesystem:
    scope: workspace
  network:
    mode: none
  shell: false
risk_level: LOW
requirements: []
compatibility:
  minimum_nexora: 2.4.0
security:
  sandbox: true
  secret_access: false
  docker_access: false
```

IDs use lowercase letters, digits, and hyphens. Versions follow Semantic
Versioning. Requirements contain only marketplace IDs; URLs and package-manager
specifications are rejected. Unknown executable fields are forbidden.
