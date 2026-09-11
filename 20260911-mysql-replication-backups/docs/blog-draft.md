# Draft: A MySQL source–replica cluster on a laptop, with backups, failover, and Grafana

*Working notes for a blog post. Every count and log line below is from the lab in this repo (kind + Ansible) on 2026-09-10 — not invented.*

## Hook

You can run a **MySQL source plus replicas**, **Orchestrator failover**, **XtraBackup to MinIO**, and **Prometheus / Grafana** on a single Docker host. The installer is Ansible; the source of truth at runtime is Kubernetes.

## What we deployed

- **kind** cluster `mysql-lab`: 1 control-plane + 2 workers
- **Percona Operator for MySQL** Helm chart `1.2.0`
- **Percona Server** `8.4.10-10`, async GTID replication, HAProxy in front
- **sysbench** `oltp_read_write` prepare: **10 tables**, **200000 rows** each, **471–493 MB** InnoDB
- **kube-prometheus-stack** `88.5.2` + `mysqld_exporter` sidecar, Prometheus job `mysql`

Diagrams: [how-it-works.md](how-it-works.md). Layout and SQL: [cluster-and-data.md](cluster-and-data.md).

## One-liner path for the reader

```bash
./scripts/lab.sh bootstrap
./scripts/lab.sh deploy
./scripts/lab.sh load-data
./scripts/lab.sh verify
```

`make deploy` PLAY RECAP: `ok=40 failed=0`. Grafana `http://127.0.0.1:3001/login` returned **200**. Prometheus `/-/ready` was ready.

## Measured results

### Dataset (`make load-data` then `make verify`)

`information_schema` after `ANALYZE TABLE`:

```
SYSBENCH_TABLES=10
SIZE_MB=471
```

After backup/restore the same query reported `SIZE_MB=493` (ANALYZE + InnoDB stats). Row counts:

```
sbtest1  → 200000
sbtest10 → 200000
```

Verify topology after scale-out:

```
POD lab-mysql-0 hostname=lab-mysql-0 read_only=0
POD lab-mysql-1 hostname=lab-mysql-1 read_only=1 replica_io=ON replica_sql=ON
POD lab-mysql-2 hostname=lab-mysql-2 read_only=1 replica_io=ON replica_sql=ON
PRIMARY=lab-mysql-0
REPLICA_OK=2
SYSBENCH_TABLES=10
SIZE_MB=493
Prometheus mysql up ok
```

Prometheus `up{job="mysql"}` returned **1** for all three exporter sidecars (`lab-mysql-0`, `lab-mysql-1`, `lab-mysql-2`).

### Failover (`make failover`)

The current source was **force-deleted** (`kubectl delete pod --force --grace-period=0`) and Orchestrator `GET /api/recover/<host>/3306` was called. Recaptured `make failover` (`failed=0`):

```
PRIMARY_BEFORE=lab-mysql-2
PRIMARY_AFTER=lab-mysql-0
OLD_READ_ONLY=1
OLD_REPLICA_IO=ON
OLD_REPLICA_SQL=ON
OLD_SOURCE_HOST=lab-mysql-0.lab-mysql.mysql
FOLLOWER lab-mysql-1 read_only=1 replica_io=ON replica_sql=ON source=lab-mysql-0.lab-mysql.mysql
FOLLOWER lab-mysql-2 read_only=1 replica_io=ON replica_sql=ON source=lab-mysql-0.lab-mysql.mysql
FOLLOWERS_OK=2
REJOIN_OK=1
```

The former source (`lab-mysql-2`) is Running, read-only, applying the new source's GTID stream. The remaining replica (`lab-mysql-1`) already followed `lab-mysql-0` before the old pod finished catching up.

### Backup and whole-cluster restore (`make backup` / `make restore`)

On-demand XtraBackup:

```
backupSource: lab-mysql-0.lab-mysql.mysql
destination: s3://mysql-lab-backups/lab/lab-2026-09-10-19:19:11-full
state: Succeeded
```

Restore playbook created `sbtest.canary_after_backup` **after** that backup, then applied `PerconaServerMySQLRestore` `lab-restore`. After restore:

- canary table count **0** (the post-backup write is gone)
- sysbench tables still **10**, size **493 MB**
- cluster `state=ready`

That is a whole-cluster restore: the operator paused MySQL, ran `xb-restore-lab-restore`, and brought both members back from the MinIO object.

### Scale-out (`make scale-out`)

`kubectl patch` `spec.mysql.size` **2 → 3**. After catch-up:

```
MYSQL_PODS=3
POD lab-mysql-0 read_only=0 tables=10
POD lab-mysql-1 read_only=1 tables=10 replica_io=ON replica_sql=ON
POD lab-mysql-2 read_only=1 tables=10 replica_io=ON replica_sql=ON
REPLICA_OK=2
```

CR status: `mysql.ready=3 size=3 state=ready`.

## Pitfalls worth a sidebar

- This operator's **async** topology is the one that matches binlog/GTID source–replica. The sibling PXC operator is Galera; do not substitute it.
- Lab size 2 needs `unsafeFlags.mysqlSize` (the operator prefers 3). Orchestrator size 1 needs `unsafeFlags.orchestratorSize`.
- Backups go to **MinIO** because XtraBackup wants S3-compatible storage, not a laptop AWS account.
- `information_schema` sizes are **wrong until `ANALYZE TABLE`**. Without it, 10×200k rows looked like 109 MB; after ANALYZE they were ~471 MB.
- `mysqld_exporter` v0.16 wants `MYSQLD_EXPORTER_PASSWORD` + `--mysqld.username`, not `DATA_SOURCE_NAME`.
- Operator pod labels are `component=database` / `component=proxy`, not `mysql` / `haproxy`.
- `SIGSTOP` on PID 1 did **not** freeze mysqld in this image; the shipped playbook force-deletes the source pod and waits for replica rejoin.
- Host ports are **3307 / 3001 / 9091** so they do not clash with the ClickHouse lab on 3306/3000/9090.

## Teardown

```bash
./scripts/lab.sh teardown
```
