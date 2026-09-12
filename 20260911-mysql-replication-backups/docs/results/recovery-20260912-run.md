# Backup, restore and PITR test run `recovery-20260912`

Generated from the recorded JSONL evidence by `./scripts/lab.sh report` (also called by the full suite). Rows represent attempts; repeated scenario IDs are retries, and absent scenarios were not recorded.

- Cluster: kind `mysql-lab`, namespace `mysql`, Percona Operator for MySQL `1.2.0`
- MySQL: `percona/percona-server:8.4.10-10.1`, 2 nodes, async GTID replication
- Backup storage: MinIO bucket `mysql-lab-backups`; binlogs: `mysql-lab-binlogs`
- Dataset: sysbench `10` tables x `200000` rows

## Summary

Coverage: 1/12 distinct scenarios recorded. A partial or repeated run is not a complete suite pass.

| # | Scenario | Result | Duration |
| --- | --- | --- | --- |
| t07 | Whole-cluster restore rolls back post-backup writes | **PASS** | 161s |
| t07 | Whole-cluster restore rolls back post-backup writes | **PASS** | 161s |

Passed 2 of 2.
Total scenario time: 322s.

## Detail

### t07 — Whole-cluster restore rolls back post-backup writes

Result: **PASSED** in 161s.

```
PRIMARY=lab-mysql-0
CANARY_BEFORE_RESTORE=1
RESTORE_BACKUP=t01-full
RESTORE_STATE=Succeeded
RESTORED_TABLES=10
RESTORED_SIZE_MB=504
CANARY_AFTER_RESTORE=0
HEALTH=PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running lab-binlog-server-r-t10-restore-0=Running 
```

### t07 — Whole-cluster restore rolls back post-backup writes

Result: **PASSED** in 161s.

```
PRIMARY=lab-mysql-0
CANARY_BEFORE_RESTORE=1
RESTORE_BACKUP=t01-full
RESTORE_STATE=Succeeded
RESTORED_TABLES=10
RESTORED_SIZE_MB=504
CANARY_AFTER_RESTORE=0
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

