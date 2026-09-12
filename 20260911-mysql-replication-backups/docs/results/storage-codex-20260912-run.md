# Backup, restore and PITR test run `storage-codex-20260912`

Generated from the recorded JSONL evidence by `./scripts/lab.sh report` (also called by the full suite). Rows represent attempts; repeated scenario IDs are retries, and absent scenarios were not recorded.

- Cluster: kind `mysql-lab`, namespace `mysql`, Percona Operator for MySQL `1.2.0`
- MySQL: `percona/percona-server:8.4.10-10.1`, 2 nodes, async GTID replication
- Backup storage: MinIO bucket `mysql-lab-backups`; binlogs: `mysql-lab-binlogs`
- Dataset: sysbench `10` tables x `200000` rows

## Summary

Coverage: 1/12 distinct scenarios recorded. A partial or repeated run is not a complete suite pass.

| # | Scenario | Result | Duration |
| --- | --- | --- | --- |
| t04 | Backup and binlog objects present in MinIO | **FAIL** | 2s |
| t04 | Backup and binlog objects present in MinIO | **FAIL** | 11s |
| t04 | Backup and binlog objects present in MinIO | **PASS** | 25s |

Passed 1 of 3.
Total scenario time: 38s.

## Detail

### t04 — Backup and binlog objects present in MinIO

Result: **FAILED** in 2s.

```
non-zero return code
```

### t04 — Backup and binlog objects present in MinIO

Result: **FAILED** in 11s.

```
non-zero return code
```

### t04 — Backup and binlog objects present in MinIO

Result: **PASSED** in 25s.

```
BACKUP_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-08:43:25-full
BACKUP_CHUNKS=122
BACKUP_BYTES=689211836
MD5_OBJECTS=1
CONTROLLED_WRITE_ROWS=20000
BINLOG_BYTES_BEFORE=426109649
BINLOG_BYTES_AFTER=446912674
BINLOG_BYTE_GROWTH=20803025
```

