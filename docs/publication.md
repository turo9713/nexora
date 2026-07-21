# First public repository publication

The current administrator repository retains private operational history and
the `v1.8.0` rollback tag. It must not be mirrored wholesale to a public remote.

Use the verified `release-artifacts/nexora-2.0.0.tar.gz` as the public source:

1. Verify its adjacent SHA-256 checksum.
2. Extract into a new empty directory.
3. Run the test, security, Compose, demo, and installation checks again.
4. Initialize a new Git repository and create the public root commit.
5. Add the public remote only after an administrator reviews the staged tree.
6. Tag that reviewed public commit `v2.0.0` and let `release.yml` publish it.

Do not push the administrator repository's `main`, private branches, reflogs,
bundles, backups, or all tags. This preserves local rollback while ensuring the
public repository never receives private operational history.
