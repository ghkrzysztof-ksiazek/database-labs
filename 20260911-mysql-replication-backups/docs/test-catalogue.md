# The twelve scenarios

Measured validation: **12/12 scenarios passed** — [ordered run report](results/20260912T101400Z-validation-run.md).

Each scenario is one Ansible role under [`../ansible/roles/`](../ansible/roles/) and one playbook under [`../ansible/playbooks/tests/`](../ansible/playbooks/tests/). Every one runs alone, and every one records its verdict, duration and raw evidence to `docs/results/<run_id>.jsonl`, which is rendered into a run report.

```bash
./scripts/lab.sh test-backups     # all twelve, in order, then the report
./scripts/lab.sh t09              # just one
RUN_ID=<id> ./scripts/lab.sh report   # re-render a run's report
```

Order is load-bearing: every restore needs a good backup behind it, and the destructive scenarios must leave the lab usable for the next one. Each scenario gates on cluster health before it starts and, where it changed anything, after it finishes.

## The three groups

| Group | Scenarios | What it establishes |
| --- | --- | --- |
| Backups are produced | t01–t06 | Objects get created, on demand and on a schedule, from the right pod, in the right place, and old ones get pruned |
| Backups restore | t07–t11 | The data comes back — whole, after a mistake, and to a chosen point in time — and a bad request fails instead of lying |
| **Backups are usable** | **t12** | **The restored copy is a real, consistent database: it replicates from production and catches up** |

All three groups contribute evidence. The third adds the operational proof that a separate restored database can replicate, catch up and match the source. A restore job reporting `Succeeded` is not sufficient on its own.

---

## t01 — On-demand full backup to MinIO

**Proves:** a `PerconaServerMySQLBackup` produces a real object in object storage.
**Method:** records table count, size and `@@GLOBAL.gtid_executed` first, then creates a `type: full` backup and waits for it.
**Asserts:** state is `Succeeded`; `status.destination` points into the backup bucket; MinIO reports non-zero usage under the cluster prefix.
**Run it:** `./scripts/lab.sh t01`

## t02 — Backup taken from the replica, primary untouched

**Proves:** `sourcePod` moves the backup's read load and locking off the pod serving writes.
**Method:** finds the pod with `@@read_only = 1`, backs up with `sourcePod` set to it, and writes to the primary while the backup runs.
**Asserts:** backup succeeds; the reported backup source matches the selected read-only replica and differs from the detected primary; the primary reported `@@read_only = 0` and accepted a test write after the backup request. This is a sampled availability check, not a continuous latency measurement.
**Run it:** `./scripts/lab.sh t02`

## t03 — Incremental backup on a full base

**Proves:** `type: incremental` with `incrementalBaseBackupName` captures only what changed.
**Method:** writes 50,000 new rows after t01's full backup, then takes an incremental against it and measures both in MinIO with `mc du --json`.
**Asserts:** state is `Succeeded`; `status.type` is `incremental`; the incremental's byte count is greater than zero and strictly smaller than the full's.
**Run it:** `./scripts/lab.sh t03`

## t04 — Backup and binlog objects present in MinIO

**Proves:** the objects are real, and the binlog stream is live rather than merely configured.
**Method:** inspects t01 backup chunks and its MD5 sidecar, writes 20,000 random-payload rows, rotates binary logs, and polls the active archive for byte growth.
**Asserts:** backup chunks and MD5 objects have nonzero size; archived binlog bytes increase after controlled writes.
**Run it:** `./scripts/lab.sh t04`

## t05 — Scheduled backup runs unattended

**Proves:** the operator's cron produces backups with nobody watching.
**Method:** records existing `percona.com/backup-type=cron` objects, patches `spec.backup.schedule` to a three-minute schedule, waits for a *new* cron backup to reach `Succeeded`, and restores the exact prior schedule before recording PASS.
**Asserts:** the new object carries `backup-type: cron` and an ancestor label naming the test schedule, and its destination is in the backup bucket.
**Run it:** `./scripts/lab.sh t05`

## t06 — Retention prunes scheduled backups down to keep

**Proves:** `keep: N` is enforced, and pruning removes the data as well as the object.
**Method:** patches a three-minute schedule with `keep: 2`, accumulates successful backup names and destinations, and checks storage after their CRs are pruned. Restores the prior schedule.
**Asserts:** at least three successful backups observed (existing successful schedule history counts); exactly two successful backups survive; removed backup data prefixes are empty. Any sibling MD5 sidecars remaining are reported separately.
**Run it:** `./scripts/lab.sh t06`

## t07 — Whole-cluster restore rolls back post-backup writes

**Proves:** a restore genuinely replaces the cluster's state, rather than merging into it.
**Method:** creates a canary table *after* the backup was taken, restores t01's backup over the running cluster, waits for the cluster to come back.
**Asserts:** restore succeeded; the canary is gone; all ten sysbench tables and the expected data size are back; the cluster is healthy with the replica running.
**Run it:** `./scripts/lab.sh t07`

## t08 — Restore recovers a dropped table

**Proves:** the ordinary disaster is survivable.
**Method:** counts the rows in `sbtest10`, drops the table, confirms it is gone, restores.
**Asserts:** the table is back with exactly the row count it had before the drop.
**Run it:** `./scripts/lab.sh t08`

## t09 — Point-in-time recovery to a timestamp

**Proves:** recovery can land between two known writes.
**Method:** takes a fresh base backup, inserts a `good` marker, waits, captures `UTC_TIMESTAMP()` as the target, waits, inserts a `bad` marker, then pauses long enough for the binlog server to checkpoint both to MinIO before restoring with `pitr.type: date`.
**Asserts:** restore succeeded; the `good` marker is present; the `bad` marker is absent; all ten sysbench tables are intact.
**Run it:** `./scripts/lab.sh t09`

## t10 — Point-in-time recovery to a GTID

**Proves:** recovery can be aimed at an exact transaction boundary rather than a clock reading.
**Method:** captures inherited GTIDs before its base backup, writes a `keep-me` marker, computes `GTID_SUBTRACT` up to the desired boundary, then commits the damage — a `DELETE` with no `WHERE` against `sbtest9` — plus a second marker. Restores with `pitr.type: gtid` aimed at that difference; inherited transactions are supplied by the base backup.
**Asserts:** `sbtest9` is back to its pre-damage row count; the `keep-me` marker survives; the post-damage marker is absent.
**Run it:** `./scripts/lab.sh t10`

## t11 — An impossible recovery target fails cleanly

**Proves:** a request that cannot be satisfied is reported, not silently downgraded.
**Method:** asks for `pitr.type: date` at `2001-01-01T00:00:00`, years before any backup or binlog exists.
**Asserts:** the restore rejects the timestamp as too old; the failed object is removed; before/after checksums match and the cluster is healthy.
**Run it:** `./scripts/lab.sh t11`

## t12 — Restore into a new cluster, attach as a replica, catch up

**Proves:** the restored database can resume replication, catch up and match the live source.

**Method:**

1. Takes its own full backup, so it depends on no earlier scenario.
2. Copies `lab-secrets` and the operator-generated `internal-lab` secret to `verify-secrets` and `internal-verify`. Without this the new cluster cannot authenticate against the data it restores, because the restored `mysql.user` table belongs to the source cluster.
3. Creates a second `PerconaServerMySQL` named `verify` — one node, no Orchestrator, no HAProxy, no PITR.
4. Requests restore into `verify` using `backupSource.destination` and the original storage configuration.
5. Writes a fresh 20,000-row marker to the live cluster after requesting restore; asserts it is absent from the restored backup before replication.
6. Points `verify` at the live primary with `SOURCE_AUTO_POSITION = 1` and starts replication. XtraBackup restored `gtid_purged`, so no binary-log coordinates are needed.
7. Waits for catch-up, then compares.

**Asserts:** `Replica_IO_Running` and `Replica_SQL_Running` are both `Yes`; `Seconds_Behind_Source` reaches 0; the 20,000 rows written after the backup are present on `verify`; `CHECKSUM TABLE` matches on all ten sysbench tables.

**Cleans up:** deletes the `verify` cluster, its restore object, its copied secrets and its PVCs, so the lab is left as it was found.

**Run it:** `./scripts/lab.sh t12`

## Prerequisites and evidence limits

Run `deploy` and `load-data` first. t03, t04, t07 and t08 require a successful `t01-full`; t11 requires `t09-base`. t09, t10 and t12 take their own bases. The full suite stops at the first failure and renders the partial report; do not continue destructive scenarios against a damaged dataset.

Each PITR scenario starts a fresh binlog prefix before its base backup, isolating the new recovery history from transactions discarded by earlier restores. t10 captures MySQL output with `--raw` to avoid escaped newlines in a multi-UUID GTID set. t11 compares table checksums before and after the expected rejection.

t04 requires nonzero XtraBackup chunks and MD5 metadata, then proves archived binlog bytes grow after controlled writes. t06 observes successful scheduled backups, verifies pruned data prefixes are empty, and reports residual MD5 sidecars separately. It restores the schedule that was active before the test.

t12 requires distinct server identities, an absent fresh marker before replication, a reached source GTID watermark, zero checksum mismatches, and all ten tables at 200,000 rows. It records restore duration, catch-up duration and the initial GTID gap. Its PASS follows cleanup and source health validation.

t03 validates incremental creation and size, not restoration of an incremental chain. In-place restore tests and replica verification provide complementary evidence; neither substitutes for application-specific recovery checks.
