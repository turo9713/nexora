# Autonomous Planning Engine

The v3.0 planning engine compiles a goal into bounded, declarative steps. Every proposed tool is checked by Agent Security and Policy Engine before a plan becomes `READY`. Planning does not execute steps, call shell, access secrets, or mutate production.

Lifecycle: `DRAFT -> VALIDATED -> WAITING_APPROVAL|READY -> RUNNING -> COMPLETED|FAILED|CANCELLED`. Medium/high-risk execution remains subject to the existing one-time approval engine.
