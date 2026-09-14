# Fixtures

- `synthetic/` contains fictional, commit-safe inputs used by automated tests.
- `private/` is ignored by Git and is the only permitted location for real statements, captured Shortcut bodies, expected normalized outputs, and parser diagnostics.

Never copy a real financial artifact into `synthetic/`, issue comments, test snapshots, or logs.
