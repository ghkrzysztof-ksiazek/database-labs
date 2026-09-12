# The twelve scenarios

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

Only the third group is verification. The first two are necessary and prove nothing on their own — a backup that restores into a subtly broken data directory can still report `Succeeded`.

---

## t01 — On-demand full backup to MinIO

**Proves:** a `PerconaServerMySQLBackup` produces a real object in object storage.
**Method:** records table count, size and `@@GLOBAL.gtid_executed` first, then creates a `type: full` backup and waits for it.
**Asserts:** state is `Succeeded`; `status.destination` points into the backup bucket; MinIO reports non-zero usage under the cluster prefix.
**Run it:** `./scripts/lab.sh t01`

## t02 — Backup taken from the replica, primary untouched

**Proves:** `sourcePod` moves the backup's read load and locking off the pod serving writes.
**Method:** finds the pod with `@@read_only = 1`, backs up with `sourcePod` set to it, and writes to the primary while the backup runs.
**Asserts:** backup succeeds; the chosen pod is not `lab-mysql-0`; the primary reported `@@read_only = 0` and accepted its writes throughout.
**Run it:** `./scripts/lab.sh t02`

## t03 — Incremental backup on a full base

**Proves:** `type: incremental` with `incrementalBaseBackupName` captures only what changed.
**Method:** writes 50,000 new rows after t01's full backup, then takes an incremental against it and measures both in MinIO with `mc du --json`.
**Asserts:** state is `Succeeded`; `status.type` is `incremental`; the incremental's byte count is greater than zero and strictly smaller than the full's.
**Run it:** `./scripts/lab.sh t03`

## t04 — Backup and binlog objects present in MinIO

**Proves:** the objects are real, and the binlog stream is live rather than merely configured.
**Method:** lists the backup bucket recursively, counts objects in the binlog bucket, waits 90 seconds (three `checkpointInterval`s), counts again.
**Asserts:** `xtrabackup` objects exist and none are zero-length; the binlog bucket is non-empty and has not shrunk across the window.
**Run it:** `./scripts/lab.sh t04`

## t05 — Scheduled backup runs unattended

**Proves:** the operator's cron produces backups with nobody watching.
**Method:** records existing `percona.com/backup-type=cron` objects, patches `spec.backup.schedule` to a three-minute schedule, waits for a *new* cron backup to reach `Succeeded`, and restores the shipped schedule in an `always` block.
**Asserts:** the new object carries `backup-type: cron` and an ancestor label naming the test schedule, and its destination is in the backup bucket.
**Run it:** `./scripts/lab.sh t05`

## t06 — Retention prunes scheduled backups down to keep

**Proves:** `keep: N` is enforced, and pruning removes the data as well as the object.
**Method:** patches the schedule to run every three minutes with `keep: 2`, waits until more than `keep` backups have been produced, pauses for a pruning cycle, then counts survivors and lists the bucket.
**Asserts:** more than `keep` were produced; at most `keep` survive; at least one named backup is gone.
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
**Method:** writes a `keep-me` marker, captures `@@GLOBAL.gtid_executed`, then commits the damage — a `DELETE` with no `WHERE` against `sbtest9` — plus a second marker. Restores with `pitr.type: gtid` aimed at the captured set.
**Asserts:** `sbtest9` is back to its pre-damage row count; the `keep-me` marker survives; the post-damage marker is absent.
**Run it:** `./scripts/lab.sh t10`

## t11 — An impossible recovery target fails cleanly

**Proves:** a request that cannot be satisfied is reported, not silently downgraded.
**Method:** asks for `pitr.type: date` at `2001-01-01T00:00:00Z`, years before any backup or binlog exists.
**Asserts:** the restore reaches a failed state with a non-empty `stateDescription`; the failed object is removed; the cluster and all ten tables survive untouched.
**Run it:** `./scripts/lab.sh t11`

## t12 — Restore into a new cluster, attach as a replica, catch up

**Proves:** the backup is a usable database — the only scenario here that does.

**Method:**

1. Takes its own full backup, so it depends on no earlier scenario.
2. Copies `lab-secrets` and the operator-generated `internal-lab` secret to `verify-secrets` and `internal-verify`. Without this the new cluster cannot authenticate against the data it restores, because the restored `mysql.user` table belongs to the source cluster.
3. Creates a second `PerconaServerMySQL` named `verify` — one node, no Orchestrator, no HAProxy, no PITR.
4. Writes 20,000 rows to the *live* cluster, so the backup is provably stale before the restore even lands.
5. Restores into `verify` using `backupSource.destination` — the object-storage path, not the source cluster's backup object.
6. Points `verify` at the live primary with `SOURCE_AUTO_POSITION = 1` and starts replication. XtraBackup restored `gtid_purged`, so no binary-log coordinates are needed.
7. Waits for catch-up, then compares.

**Asserts:** `Replica_IO_Running` and `Replica_SQL_Running` are both `Yes`; `Seconds_Behind_Source` reaches 0; the 20,000 rows written after the backup are present on `verify`; `CHECKSUM TABLE` matches on all ten sysbench tables.

**Cleans up:** deletes the `verify` cluster, its restore object, its copied secrets and its PVCs, so the lab is left as it was found.

**Run it:** `./scripts/lab.sh t12`
