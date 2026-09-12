# Diagrams

Each file is a standalone Mermaid diagram:

- `architecture.mmd`: backup creation and binlog streaming.
- `pitr.mmd`: physical restore followed by binlog replay.
- `restore-as-replica.mmd`: restore a separate cluster, attach replication and compare data.

Render a file with `mmdc -i architecture.mmd -o architecture.svg` or paste its contents into a Mermaid viewer.
