# Contributing a community skill

1. Copy the safe example under `examples/`.
2. Declare only the permissions needed by the skill.
3. Add unit, validation, and denied-permission tests.
4. Document inputs, outputs, limitations, and expected audit events.
5. Run the repository test and security suites.
6. Submit a pull request for validation and security review.

Approval never grants shell, root, secrets, Docker, or production access.
