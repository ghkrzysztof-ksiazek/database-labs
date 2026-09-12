# Backup, restore and PITR test run `20260912T101400Z-validation`

Generated from the recorded JSONL evidence by `./scripts/lab.sh report` (also called by the full suite). Rows represent attempts; repeated scenario IDs are retries, and absent scenarios were not recorded.

- Cluster: kind `mysql-lab`, namespace `mysql`, Percona Operator for MySQL `1.2.0`
- MySQL: `percona/percona-server:8.4.10-10.1`, 2 nodes, async GTID replication
- Backup storage: MinIO bucket `mysql-lab-backups`; binlogs: `mysql-lab-binlogs`
- Dataset: sysbench `10` tables x `200000` rows

## Summary

Coverage: 12/12 distinct scenarios recorded. A partial or repeated run is not a complete suite pass.

| # | Scenario | Result | Duration |
| --- | --- | --- | --- |
| t01 | On-demand full backup to MinIO | **PASS** | 27s |
| t02 | Backup taken from the replica, primary untouched | **PASS** | 14s |
| t03 | Incremental backup on a full base | **PASS** | 19s |
| t04 | Backup and binlog objects present in MinIO | **PASS** | 40s |
| t05 | Scheduled backup runs unattended | **PASS** | 207s |
| t06 | Retention prunes scheduled backups down to keep | **PASS** | 11s |
| t07 | Whole-cluster restore rolls back post-backup writes | **PASS** | 161s |
| t08 | Restore recovers a dropped table | **PASS** | 160s |
| t09 | Point-in-time recovery to a timestamp | **PASS** | 355s |
| t10 | Point-in-time recovery to a GTID | **PASS** | 336s |
| t11 | An impossible recovery target fails cleanly | **PASS** | 24s |
| t12 | Restore into a new cluster, attach as a replica, catch up | **PASS** | 118s |

Passed 12 of 12.
Total scenario time: 1472s.

## Detail

### t01 — On-demand full backup to MinIO

Result: **PASSED** in 27s.

```
TABLES=10
SIZE_MB=504
GTID_AT_BACKUP=5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,\nf25e09c8-ae91-11f1-b5a6-72d21a7478f2:1-212
BACKUP_STATE=Succeeded
BACKUP_TYPE=full
BACKUP_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:13:48-full
BACKUP_COMPLETED=2026-09-12T10:13:58Z
MINIO_USAGE=10GiB	2353 objects	mysql-lab-backups/lab
```

### t02 — Backup taken from the replica, primary untouched

Result: **PASSED** in 14s.

```
SOURCE_POD=lab-mysql-1
ACTUAL_BACKUP_SOURCE=lab-mysql-1.lab-mysql.mysql
BACKUP_STATE=Succeeded
BACKUP_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:14:15-full
BACKUP_COMPLETED=2026-09-12T10:14:24Z
PRIMARY_WRITABLE=yes
PRIMARY_WRITES=2
```

### t03 — Incremental backup on a full base

Result: **PASSED** in 19s.

```
DELTA_ROWS=100000
BASE_BACKUP=t01-full
FULL_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:13:48-full
INCR_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:13:48-full.incr/lab-2026-09-12-10:14:30-incr
FULL_BYTES=708418853
INCR_BYTES=15510469
INCR_PCT_OF_FULL=2
```

### t04 — Backup and binlog objects present in MinIO

Result: **PASSED** in 40s.

```
BACKUP_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:13:48-full
BACKUP_CHUNKS=127
BACKUP_BYTES=708418853
MD5_OBJECTS=1
CONTROLLED_WRITE_ROWS=20000
BINLOG_BYTES_BEFORE=42303809
BINLOG_BYTES_AFTER=63112573
BINLOG_BYTE_GROWTH=20808764
```

### t05 — Scheduled backup runs unattended

Result: **PASSED** in 207s.

```
SCHEDULE_PATCHED=*/3 * * * * name=suite-fast
PRE_EXISTING_CRON_BACKUPS=3
NEW_BACKUP=cron-lab-minio-20260912101829-efvvj
NEW_BACKUP_ANCESTOR=f7ac8-suite-fast
NEW_BACKUP_STATE=Succeeded
NEW_BACKUP_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:18:29-full
NEW_BACKUP_COMPLETED=2026-09-12T10:18:40Z
```

### t06 — Retention prunes scheduled backups down to keep

Result: **PASSED** in 11s.

```
SCHEDULE=*/3 * * * *
KEEP=2
PRODUCED_COUNT=3
PRODUCED=cron-lab-minio-20260912090638-mu0gh,cron-lab-minio-20260912090938-mu0gh,cron-lab-minio-20260912101829-efvvj
SURVIVING_COUNT=2
SURVIVING=cron-lab-minio-20260912090938-mu0gh,cron-lab-minio-20260912101829-efvvj
PRUNED=cron-lab-minio-20260912090638-mu0gh
REMOVED_DATA_PREFIX=s3://mysql-lab-backups/lab/lab-2026-09-12-09:06:38-full/
MD5_SIDECARS_REMAINING=["lab-2026-09-12-09:06:38-full.md5"]
RETENTION_SCOPE=successful backup CRs and data prefixes; sibling MD5 sidecars reported separately
```

### t07 — Whole-cluster restore rolls back post-backup writes

Result: **PASSED** in 161s.

```
PRIMARY=lab-mysql-0
CANARY_BEFORE_RESTORE=1
RESTORE_BACKUP=t01-full
RESTORE_STATE=Succeeded
RESTORED_TABLES=10
RESTORED_SIZE_MB=511
CANARY_AFTER_RESTORE=0
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

### t08 — Restore recovers a dropped table

Result: **PASSED** in 160s.

```
ROWS_BEFORE_DROP=200000
TABLES_AFTER_DROP=9
RESTORE_STATE=Succeeded
TABLES_AFTER_RESTORE=10
ROWS_AFTER_RESTORE=200000
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

### t09 — Point-in-time recovery to a timestamp

Result: **PASSED** in 355s.

```
BASE_BACKUP=t09-base
BASE_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:24:35-full
GOOD_MARKER_AT=2026-09-12 10:24:47.265418
PITR_TARGET=2026-09-12T10:25:07
BAD_MARKER_AT=2026-09-12 10:25:27.838550
MARKERS_BEFORE_RESTORE=good-1789208667,bad-1789208667
PITR_TYPE=date
PITR_TARGET=2026-09-12T10:25:07
RESTORE_STATE=Succeeded
GOOD_AFTER_RESTORE=1
BAD_AFTER_RESTORE=0
TABLES_AFTER_RESTORE=10
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

### t10 — Point-in-time recovery to a GTID

Result: **PASSED** in 336s.

```
BASE_BACKUP=t10-base
BASE_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:30:31-full
ROWS_BEFORE_DAMAGE=200000
INHERITED_GTIDS=5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,a84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:1-38,d97cef97-ae93-11f1-ba46-16c9a8133dba:1-71,f25e09c8-ae91-11f1-b5a6-72d21a7478f2:1-214
GTID_TARGET=a84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:39-52
ROWS_AFTER_DAMAGE=0
PITR_TYPE=gtid
PITR_TARGET=a84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:39-52
RESTORE_STATE=Succeeded
ROWS_AFTER_RESTORE=200000
KEEP_MARKER=1
DAMAGE_MARKER=0
GTID_AFTER_RESTORE=5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,\n71463f98-ae95-11f1-aeda-1e96d50fb941:1-27,\na84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:1-52,\nd97cef97-ae93-11f1-ba46-16c9a8133dba:1-71,\nf25e09c8-ae91-11f1-b5a6-72d21a7478f2:1-214
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

### t11 — An impossible recovery target fails cleanly

Result: **PASSED** in 24s.

```
PITR_TYPE=date
PITR_TARGET=2001-01-01T00:00:00 (valid format, before any backup or binlog existed)
RESTORE_STATE=Error
RESTORE_REASON=reconcile pitr config: search binlogs: search binlogs: exec binlog_server search_by_timestamp: stdout: {"version":1,"status":"error","message":"Timestamp is too old"}
 stderr: : command terminated with exit code 1
TABLES_AFTER_FAILED_RESTORE=10
HEALTH=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running lab-binlog-server-r-t11-restore-0=Running 
```

### t12 — Restore into a new cluster, attach as a replica, catch up

Result: **PASSED** in 118s.

```
BASE_BACKUP=t12-base
BASE_DESTINATION=s3://mysql-lab-backups/lab/lab-2026-09-12-10:36:24-full
COPIED lab-secrets -> verify-secrets
COPIED internal-lab -> internal-verify
COPIED lab-ssl -> verify-ssl
WRITES_AFTER_BACKUP=20000
RESTORE_TARGET_CLUSTER=verify
RESTORE_STATE=Succeeded
SERVER_UUID live=71463f98-ae95-11f1-aeda-1e96d50fb941 restored=e55cafc3-ae95-11f1-a099-1e881dd5cec9
SERVER_ID live=35921690 restored=39133310
RESTORE_SECONDS=65
RESTORED_GTID_PURGED=5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,71463f98-ae95-11f1-aeda-1e96d50fb941:1-55,a84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:1-52,d97cef97-ae93-11f1-ba46-16c9a8133dba:1-71,f25e09c8-ae91-11f1-b5a6-72d21a7478f2:1-214
RESTORED_TABLES=10
RESTORED_POST_BACKUP_ROWS=0
SOURCE_HOST=lab-mysql-0.lab-mysql.mysql.svc.cluster.local
REPLICATION_STARTED=yes
Replica_IO_Running: Yes
Replica_SQL_Running: Yes
Seconds_Behind_Source: 0
Last_IO_Error: 
Last_SQL_Error: 
Replica_SQL_Running_State: Replica has read all relay log; waiting for more updates
Last_IO_Error_Timestamp: 
Last_SQL_Error_Timestamp: 
Retrieved_Gtid_Set: 71463f98-ae95-11f1-aeda-1e96d50fb941:56-154
Executed_Gtid_Set: 5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,
CATCHUP_SECONDS=12
RESTORED_GTID_SUBSET=1
SOURCE_GTID_SUBSET=1
GTID_GAP_REPLAYED=71463f98-ae95-11f1-aeda-1e96d50fb941:56-155
GTID_GAP_TRANSACTIONS=100
LIVE_POST_BACKUP_ROWS=20000
REPLICA_POST_BACKUP_ROWS=20000
ROWS sbtest1 live=200000 replica=200000
CHECKSUM sbtest1 live=2265383791 replica=2265383791
ROWS sbtest2 live=200000 replica=200000
CHECKSUM sbtest2 live=36001553 replica=36001553
ROWS sbtest3 live=200000 replica=200000
CHECKSUM sbtest3 live=3578805434 replica=3578805434
ROWS sbtest4 live=200000 replica=200000
CHECKSUM sbtest4 live=1590601991 replica=1590601991
ROWS sbtest5 live=200000 replica=200000
CHECKSUM sbtest5 live=2696283356 replica=2696283356
ROWS sbtest6 live=200000 replica=200000
CHECKSUM sbtest6 live=2743726803 replica=2743726803
ROWS sbtest7 live=200000 replica=200000
CHECKSUM sbtest7 live=134583990 replica=134583990
ROWS sbtest8 live=200000 replica=200000
CHECKSUM sbtest8 live=576143612 replica=576143612
ROWS sbtest9 live=200000 replica=200000
CHECKSUM sbtest9 live=2206676138 replica=2206676138
ROWS sbtest10 live=200000 replica=200000
CHECKSUM sbtest10 live=3590946855 replica=3590946855
CHECKSUM_MISMATCHES=0
LIVE_GTID=5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,71463f98-ae95-11f1-aeda-1e96d50fb941:1-161,a84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:1-52,d97cef97-ae93-11f1-ba46-16c9a8133dba:1-71,f25e09c8-ae91-11f1-b5a6-72d21a7478f2:1-214
REPLICA_GTID=5fccd34e-ae85-11f1-a9d5-0e01098e2e59:1-925,71463f98-ae95-11f1-aeda-1e96d50fb941:1-161,a84e643f-ae94-11f1-8ddd-2ec4c43ab3c3:1-52,d97cef97-ae93-11f1-ba46-16c9a8133dba:1-71,f25e09c8-ae91-11f1-b5a6-72d21a7478f2:1-214
VERIFY_RESOURCES_REMAINING=0
SOURCE_HEALTH_AFTER_CLEANUP=SYSBENCH_TABLES=10 | PRIMARY=lab-mysql-0 | REPLICA_OK=1 | BINLOG_SERVER=lab-binlog-server-0=Running 
```

