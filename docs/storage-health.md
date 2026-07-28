# Storage Health

Storage observability performs read-only SQLite integrity checks, verifies
private POSIX modes inside configured state roots, reports disk usage, and
indicates whether a backup artifact is visible. Responses never contain host
paths, filenames, secrets, or raw database errors.

`UNKNOWN` backup status means the process cannot confirm a backup from its
mounted view; it is not reported as healthy.
