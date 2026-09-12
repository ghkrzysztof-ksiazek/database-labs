# Backup, restore and PITR test run `pitr-codex-20260912`

Generated from the recorded JSONL evidence by `./scripts/lab.sh report` (also called by the full suite). Rows represent attempts; repeated scenario IDs are retries, and absent scenarios were not recorded.

- Cluster: kind `mysql-lab`, namespace `mysql`, Percona Operator for MySQL `1.2.0`
- MySQL: `percona/percona-server:8.4.10-10.1`, 2 nodes, async GTID replication
- Backup storage: MinIO bucket `mysql-lab-backups`; binlogs: `mysql-lab-binlogs`
- Dataset: sysbench `10` tables x `200000` rows

## Summary

Coverage: 2/12 distinct scenarios recorded. A partial or repeated run is not a complete suite pass.

| # | Scenario | Result | Duration |
| --- | --- | --- | --- |
| t09 | Point-in-time recovery to a timestamp | **PASS** | 356s |
| t10 | Point-in-time recovery to a GTID | **FAIL** | 180s |

Passed 1 of 2.
Total scenario time: 536s.

## Detail

### t09 — Point-in-time recovery to a timestamp

Result: **PASSED** in 356s.

```
BASE_BACKUP=t09-base
BASE_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-09:58:15-full
GOOD_MARKER_AT=2026-09-12 09:58:26.988353
PITR_TARGET=2026-09-12T09:58:47
BAD_MARKER_AT=2026-09-12 09:59:07.620289
MARKERS_BEFORE_RESTORE=good,bad
PITR_TYPE=date
PITR_TARGET=2026-09-12T09:58:47
RESTORE_STATE=Succeeded
GOOD_AFTER_RESTORE=1
BAD_AFTER_RESTORE=0
TABLES_AFTER_RESTORE=10
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

### t10 — Point-in-time recovery to a GTID

Result: **FAILED** in 180s.

```
PITR to 5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,9757dad9-ae8f-11f1-bc49-1a9083ac6ffc:1-323,fab3dfc8-ae90-11f1-af21-cac6f0bf3aeb:1-83 failed: {'state': 'Error', 'stateDescription': 'reconcile pitr config: search binlogs: search binlogs: exec binlog_server search_by_gtid_set: stdout: {"version":1,"status":"error","message":"The specified GTID set cannot be covered"}\n stderr: : command terminated with exit code 1'}
```

