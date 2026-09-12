# Test your MySQL backup by restoring it as a replica

A successful backup job establishes that the backup process completed. It does not establish that you can recover your database, resume replication, or meet a recovery-time objective. Those questions require a restore test.

This lab makes that test concrete: restore a physical backup into a separate MySQL cluster, configure GTID replication from the live source, let it catch up, and compare the data. The existing source continues running. The verification cluster is disposable.

## The experiment

The environment is a local kind cluster running Percona Operator for MySQL 1.2.0 and Percona Server 8.4. It retains the source and replica, HAProxy, Orchestrator, MinIO, Prometheus and Grafana from the replication lab. PITR adds a binlog server and a separate MinIO bucket. The dataset contains ten sysbench tables, each with 200,000 rows.

Twelve Ansible scenarios test full backups, backups from a replica, incremental creation, stored objects, scheduling, retention, whole-cluster restore, a dropped table, timestamp PITR, GTID PITR, invalid targets, and restore into a new cluster followed by replication. The [catalogue](test-catalogue.md) describes the assertions and prerequisites. Measured evidence is recorded in [run reports](results/); interrupted and failed shakeouts remain distinguishable from final validation.

The [second shakeout report](results/shakeout2-run.md) preserves the failures that led to these corrections. It is not a clean validation run.

## Measured ordered run — 12 September 2026

All twelve scenarios passed in one ordered run. The [generated report](results/20260912T101400Z-validation-run.md) contains the raw assertion evidence; development attempts are retained separately.

| Scenario | Duration |
| --- | --- |
| t01 — On-demand full backup to MinIO | 27 s |
| t02 — Backup taken from the replica, primary untouched | 14 s |
| t03 — Incremental backup on a full base | 19 s |
| t04 — Backup and binlog objects present in MinIO | 40 s |
| t05 — Scheduled backup runs unattended | 207 s |
| t06 — Retention prunes scheduled backups down to keep | 11 s |
| t07 — Whole-cluster restore rolls back post-backup writes | 161 s |
| t08 — Restore recovers a dropped table | 160 s |
| t09 — Point-in-time recovery to a timestamp | 355 s |
| t10 — Point-in-time recovery to a GTID | 336 s |
| t11 — An impossible recovery target fails cleanly | 24 s |
| t12 — Restore into a new cluster, attach as a replica, catch up | 118 s |

Retention began with successful scheduled backups already present from earlier development runs; its duration measures pruning and verification, not creation of three fresh backups. The removed data prefix was empty, but its sibling MD5 sidecar remained and is recorded in the report.

Total recorded scenario time: 1472 seconds. These are local-lab timings, including waits and checks, not a production benchmark.

The separate-cluster restore took 65 seconds. Catch-up took 12 seconds and replayed a measured GTID gap of 100 transactions. The fresh 20,000-row marker was absent before replication and present afterward. Both replication threads were running, lag reached zero, and all ten tables had 200,000 rows with matching checksums. Cleanup left no verification pods or PVCs; the source and its original replica remained healthy.

## The restore test that matters operationally

The verification scenario takes a fresh full backup and records its destination and storage configuration. It creates a one-node `verify` cluster with the same credentials as the source, then restores from MinIO using `backupSource`. The source backup CR is not referenced by the restore request.

Credentials matter because the physical backup contains the MySQL system tables. The new cluster must be able to authenticate against the restored accounts. The lab copies the source user secret and the operator-generated `internal-lab` secret into the verification cluster names. This is a local demonstration with intentionally simple credentials, not a production secret-management pattern.

The storage prefix matters too. A destination such as `s3://mysql-lab-backups/lab/<backup>` is not enough when the explicit S3 storage definition omits `prefix: lab`. This operator uses that definition when locating the backup. The test preserves the storage metadata from the successful backup.

After requesting the restore, the test writes a unique marker table with 20,000 rows to the live source. Those rows are newer than the backup. Before replication starts, the restored copy must not contain them.

The restored instance must have a distinct server UUID and server ID. It is attached to the source with `CHANGE REPLICATION SOURCE TO`, `SOURCE_AUTO_POSITION=1` and the replication account. The test waits for both replication threads, a captured source GTID watermark, and the marker rows. Finally, it checks exact row counts and non-NULL checksums for all ten sysbench tables. Zero seconds of lag alone is not the acceptance criterion.

The report records the restore and catch-up durations, the initial GTID gap, and the comparison evidence. Only after cleanup and a source health check does the scenario report success.

## PITR needs the correct recovery history

Timestamp recovery writes a unique good marker for this attempt, captures a UTC boundary, and writes a unique bad marker after it. The marker identity must be new; a base backup containing an old success marker cannot prove that this recovery replayed anything. GTID recovery records the inherited transaction set before its base backup, then captures the GTID difference up to the boundary before deleting the contents of a table. Recovery must retain the earlier data and exclude the later damage.

The first shakeout uncovered a subtle problem: after an in-place restore, the old archive still contained transactions from the discarded history. A later timestamp recovery replayed an earlier test's `DROP TABLE`. Its markers were correct, but the database had only nine sysbench tables. Checking the whole dataset exposed what checking only marker rows would have missed.

Each PITR scenario therefore starts a fresh archive prefix before taking its base backup. Old archives remain intact for investigation. This is explicit recovery-history management for a lab that repeatedly rewinds its source; an archive should not silently mix histories after a rollback.

Two smaller integration details also surfaced. This binlog-server build accepts UTC timestamps as `YYYY-MM-DDTHH:MM:SS`, without a timezone suffix. The sample's `Z` suffix produced `Invalid timestamp format`. And the MySQL batch client escapes embedded newlines unless raw output is requested; an escaped multiline GTID set is not a valid recovery target. The harness captures raw GTIDs and removes actual line breaks. It requests the GTID difference for the current recovery history: asking a fresh archive to cover inherited GTIDs from an older backup produced `The specified GTID set cannot be covered`.

## Test the test

An expected failure must fail for the intended reason. The negative PITR scenario initially passed on a timestamp-format error. It now requires a range/search rejection and compares the dataset before and after the request.

Retention needs a similar distinction. Seeing fewer backup CRs does not prove that storage was reclaimed. The test must remember the destinations it observed and check the pruned data prefixes in MinIO. Residual metadata should be reported separately instead of being silently described as full deletion.

The incremental scenario tests creation and relative size. It does not establish that an incremental restore chain works. That would require its own restore-and-compare test.

## Reproduce it

From `20260911-mysql-replication-backups/`:

```bash
./scripts/lab.sh deploy
./scripts/lab.sh load-data
RUN_ID=my-validation ./scripts/lab.sh test-backups
RUN_ID=my-validation ./scripts/lab.sh report
```

The suite is destructive to this local lab: several scenarios intentionally rewind the source. Run individual scenarios with `./scripts/lab.sh t01` through `t12`, observing the catalogue's backup prerequisites. Use `./scripts/lab.sh test` for the separate offline configuration checks.

The final checks also passed all 35 [offline tests](results/20260912T101400Z-validation-offline-tests.log) and the [cluster verification](results/20260912T101400Z-validation-health.log), including replica IO/SQL threads and Prometheus MySQL availability. The [environment snapshot](results/20260912T101400Z-validation-environment.json) records actual image digests, Kubernetes version and PITR archive configuration.

## What the evidence can establish

A restored replica that catches up and matches the source gives strong evidence that this backup and replication path work for the tested dataset. It does not replace application-level checks, production-scale timing, or testing other backup generations. Restore, catch up, verify, record the result, and repeat on a schedule. A backup schedule should have a matching restore-test schedule.
