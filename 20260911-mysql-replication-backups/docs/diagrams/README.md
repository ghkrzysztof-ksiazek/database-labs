# Diagrams

`architecture.mmd` holds three mermaid diagrams, in the order the lab exercises them:

1. **The backup path** — how a `PerconaServerMySQLBackup` becomes objects in MinIO, and how the binlog server streams binary logs alongside it.
2. **The point-in-time recovery path** — what the operator does to the running cluster when a restore carries a `pitr` target.
3. **The restore-as-replica path** — restoring into a separate cluster and attaching it to the live one, which is the only scenario that verifies a backup rather than merely exercising it.

Render with `mmdc -i architecture.mmd -o architecture.svg`, or paste a single block into any mermaid viewer. The file contains three `flowchart` blocks; most renderers want one at a time.
