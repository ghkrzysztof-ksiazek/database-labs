# How backups, PITR and verification work in this lab

This lab runs the [Percona Operator for MySQL](https://docs.percona.com/percona-operator-for-mysql/ps/) (`ps-operator`) `1.2.0` on a kind cluster, with Percona Server 8.4 in a one-source / one-replica async GTID topology, HAProxy in front, Orchestrator watching, and MinIO standing in for S3. Everything below describes what the operator actually does, checked against the CRDs and the recorded runs in [`results/`](results/) — not what the documentation promises.

The claim the lab exists to test is at the bottom, in *Why replication is the real test*. Everything before it is the machinery needed to get there.

## 1. What the operator does when you ask for a backup

A backup is a Kubernetes object, not a command:

```yaml
apiVersion: ps.percona.com/v1
kind: PerconaServerMySQLBackup
metadata:
  name: t01-full
spec:
  clusterName: lab
  storageName: minio
  type: full            # or: incremental
```

The operator reacts by creating an `xb-<name>-<storage>-<hash>` Job running the `percona/percona-xtrabackup:8.4.0-6.1` image. XtraBackup reads the data directory of a cluster member directly and streams the result to object storage with `xbcloud`; nothing is written to a local staging disk first.

Three fields on `spec` are worth knowing:

- **`type: incremental`** with **`incrementalBaseBackupName`** takes a backup of only the pages that changed since the named full backup.
- **`sourcePod`** pins the backup to a specific pod. Pointing it at the replica keeps the read load, and XtraBackup's brief locking, away from the pod serving writes. Scenario `t02` does exactly this and checks that the primary accepts a test write after requesting the backup.
- **`storageName`** selects one of `spec.backup.storages` on the cluster — here, the MinIO entry.

When the job finishes, the object's `status` carries the answer:

```
state:       Succeeded
destination: s3://mysql-lab-backups/lab/lab-2026-09-11-11:15:18-full
completed:   <timestamp>
type:        full
```

That `destination` string matters later: it is what lets a *different* cluster restore this backup without knowing anything about the cluster that made it.

Scheduled backups are the same object, created by the operator's own cron. They are named `cron-<cluster>-<storage>-<stamp>-<hash>` — the `xb-cron-*` names you see belong to the Jobs and Pods, not the backup objects — and they carry two labels that make them selectable:

```
percona.com/backup-type: cron
percona.com/backup-ancestor: <hash>-<schedule name>
```

`keep: N` on a schedule entry is what prunes: the operator deletes the oldest backup objects of that ancestor, and their data in object storage with them.

## 2. The binlog server, and what PITR actually needs

A full backup alone can only take you back to the instant it was taken. Recovery to an arbitrary point needs the binary logs written *since* that backup, somewhere durable. In `ps-operator` 1.2.0 that is the binlog server:

```yaml
spec:
  backup:
    pitr:
      enabled: true
      binlogServer:
        image: percona/percona-server-mysql-operator:1.2.0-binlog-server-0.4.1
        serverId: 1001
        checkpointInterval: 30s
        checkpointSize: 16M
        storage:
          s3:
            bucket: mysql-lab-binlogs
            ...
```

This deploys `lab-binlog-server-0`, which **registers with the primary as if it were an ordinary replica** — hence `serverId`, which must not collide with any real server — and streams the binary log to object storage. It applies nothing; it only stores.

Two settings define the worst-case data loss:

- **`checkpointInterval`** (30s here) — how often a partial binlog is flushed to storage.
- **`checkpointSize`** (16M here) — how much binlog accumulates before a flush regardless of the interval.

Anything written after the last checkpoint and before a total loss of the primary is gone. That, not the backup schedule, is this lab's real RPO.

The binlog bucket is deliberately separate from the backup bucket, so `mc ls` shows the two streams independently:

```
mysql-lab-binlogs/lab/binlog.000001        128MiB
mysql-lab-binlogs/lab/binlog.000001.json      212B
mysql-lab-binlogs/lab/binlog.index             48B
mysql-lab-binlogs/lab/metadata.json            27B
```

A recovery window is bounded on both sides: it begins at the oldest full backup you still have, and ends at the newest binlog checkpoint. Binlogs alone cannot recover anything — there is nothing to replay them onto — which is why retention that prunes backups also shortens the window.

## 3. Restoring in place

```yaml
apiVersion: ps.percona.com/v1
kind: PerconaServerMySQLRestore
spec:
  clusterName: lab
  backupName: t01-full
```

An in-place restore is not a background operation. The operator stops the cluster, restores the data directory from object storage, brings MySQL back, and rebuilds the replicas from the restored primary. The cluster is down for the duration — the recorded restore durations in [`results/`](results/) are the honest RTO for a dataset of this size on a laptop.

Because the whole cluster is rolled back, anything written after the backup is gone. Scenario `t07` proves that on purpose: it creates a canary table after the backup and requires it to be absent afterwards. Scenario `t08` does the useful version of the same thing — drops a table, restores, and checks the rows came back.

## 4. Point-in-time recovery

Add a `pitr` block and the operator replays binlogs on top of the restored backup:

```yaml
spec:
  clusterName: lab
  backupName: t09-base
  pitr:
    type: date                       # or: gtid
    date: "2026-09-12T09:14:05"      # NOT RFC3339 — see below
    # gtid: "f3c2...:1-4172"
    backupSource:
      binlogServer:
        image: percona/percona-server-mysql-operator:1.2.0-binlog-server-0.4.1
        serverId: 1011
        storage:
          s3: {bucket: mysql-lab-binlogs, ...}
```

Two details cost time if you get them wrong:

- The **date format is `YYYY-MM-DDTHH:MM:SS` in UTC, with no timezone suffix** — and Percona's own sample `restore.yaml` gets this wrong. It shows `date: "2024-11-18T11:10:48Z"`, and that `Z` makes the restore fail:

  ```
  reconcile pitr config: search binlogs: exec binlog_server search_by_timestamp:
  {"version":1,"status":"error","message":"Invalid timestamp format"}
  ```

  Probing `binlog_server search_by_timestamp` directly inside the binlog server pod settles it — of `2026-09-12T09:00:00Z`, `2026-09-12 09:00:00`, a Unix epoch, `2026-09-12T09:00:00+00:00` and `2026-09-12T09:00:00`, only the last is accepted. Take the value from the server with `SELECT DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%dT%H:%i:%s')`, never from the laptop's clock or timezone.
- The **`serverId` of the restore-time binlog server must not collide** with the running one, or with any MySQL instance. The scenarios use 1011, 1012 and so on against a cluster binlog server at 1001.

`type: gtid` targets a GTID set rather than a wall-clock instant, which is the precise tool when you know exactly which transaction did the damage: capture a baseline before the base backup, then use `GTID_SUBTRACT(@@GLOBAL.gtid_executed, baseline)` before the bad statement. This archive must cover the requested difference; older inherited transactions are already in the base. Scenario `t10` does that around a `DELETE` with no `WHERE` clause.

Scenario `t11` asks for a target that cannot be satisfied — a timestamp years before any backup existed — to check the operator says so rather than quietly restoring the plain backup and reporting success. What it actually did is recorded in the run report.

## 5. Restoring into a *different* cluster

This is the part with a trap in it.

A restore can name an object-storage path instead of a backup object, which decouples it from the cluster that produced it:

```yaml
spec:
  clusterName: verify          # a different cluster
  backupSource:
    destination: s3://mysql-lab-backups/lab/lab-2026-09-12-08:52:03-full
    storage:
      type: s3
      s3: {bucket: mysql-lab-backups, credentialsSecret: minio-backup-credentials, ...}
```

The trap: **the restored data directory contains the source cluster's `mysql.user` table.** A brand-new cluster gets brand-new generated passwords in its own secrets, and the moment its data directory is replaced by the restore, those passwords are wrong — the accounts in the restored data are the *old* cluster's. The operator then cannot log in to the database it has just restored, and the failure surfaces as a crash-looping cluster or a stuck restore, which reads like a corrupt backup rather than an authentication problem.

The fix is to hand the new cluster the same credentials before it starts:

```bash
kubectl get secret lab-secrets   -o json | rename-to verify-secrets   | kubectl apply -f -
kubectl get secret internal-lab  -o json | rename-to internal-verify  | kubectl apply -f -
```

`internal-<cluster>` is the operator-generated secret holding the `operator`, `replication`, `monitor`, `orchestrator`, `heartbeat` and `xtrabackup` account passwords — copying only the user-facing `lab-secrets` is not enough.

## 6. Why replication is the real test

Everything above proves a backup *exists* and can be *loaded*. Neither proves it is a usable database. A backup that restores into a corrupt or subtly incomplete data directory can still report `Succeeded`.

The test that settles it: restore into a separate cluster, then make that cluster a replica of the live one and let it catch up.

```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='lab-mysql-0.lab-mysql.mysql.svc.cluster.local',
  SOURCE_USER='replication',
  SOURCE_PASSWORD='...',
  SOURCE_SSL=1,
  SOURCE_AUTO_POSITION=1;
START REPLICA;
```

No binary-log file names, no offsets. XtraBackup restores `gtid_purged` along with the data, so the restored server already knows precisely which transactions it contains; `SOURCE_AUTO_POSITION=1` asks the primary for everything after that set. If the backup were incomplete or inconsistent, this is where it breaks — replication either refuses to start, or applies a transaction onto a row that isn't in the state the binlog expects and stops with an error.

Getting to `Seconds_Behind_Source: 0` proves four things at once that no green job status can:

1. the backup's data directory was **complete and internally consistent** — InnoDB recovered and started;
2. `gtid_purged` was **accurate** — the server's idea of what it contains matches reality, or auto-position would have asked for the wrong transactions;
3. the transactions written **after** the backup apply cleanly on top of it — the backup is a valid ancestor of the current production state, not a divergent branch;
4. the result is **byte-comparable** with production — `CHECKSUM TABLE` on all ten sysbench tables matches once writes stop.

Scenario `t12` runs exactly this, and deliberately keeps writing to the live cluster while the restore is in flight, so the restored copy has real ground to make up rather than arriving at an idle, unchanged source.

In production, a verified restored copy may be retained as a standby after the appropriate operational checks. A backup restored into a replica that then catches up *is* a standby. Verification and capacity are the same piece of work.

## Recovery histories and exact storage configuration

After an in-place rollback, the old archive can contain transactions no longer in the live database. Replaying that archive into a later backup can resurrect discarded changes. t09 and t10 allocate separate archive prefixes before taking their bases; previous archives are retained for investigation. The live logs in the second shakeout showed this failure explicitly: marker assertions passed but an old DROP TABLE was replayed.

For cross-cluster restore, preserve `backup.status.storage` alongside `status.destination`. In this lab that includes `s3.prefix: lab`. Supplying the bucket alone makes this operator search the wrong object prefix.

The deployed v1.2.0 implementation is available in the [restore controller](https://github.com/percona/percona-server-mysql-operator/blob/v1.2.0/pkg/controller/psrestore/controller.go), [S3 option builder](https://github.com/percona/percona-server-mysql-operator/blob/v1.2.0/pkg/xtrabackup/storage/options.go), and [PITR replay code](https://github.com/percona/percona-server-mysql-operator/blob/v1.2.0/cmd/pitr/main.go). Version-specific behavior above is scoped to this lab build.
