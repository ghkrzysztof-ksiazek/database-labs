# Cluster layout and data

## Topology

- Kind cluster name: `mysql-lab`
- Namespace: `mysql`
- CR: `PerconaServerMySQL/lab`
- `mysql.clusterType`: `async` (GTID source–replica)
- Initial size: 2 (1 source + 1 replica). Scale-out target: 3.
- Proxy: HAProxy (writes on 3306, reads on 3307 inside the cluster)
- Failover manager: Orchestrator (1 replica, lab-unsafe size)
- Backup store: MinIO bucket `mysql-lab-backups`

## Connection

From the host after deploy:

```bash
mysql -h 127.0.0.1 -P 3307 -uroot -pmysql
```

From inside the cluster:

```text
lab-haproxy.mysql.svc.cluster.local:3306   # current source
```

Kubeconfig: `.kube/config` in this directory.

## sysbench dataset

| Knob | Value |
| --- | --- |
| Database | `sbtest` |
| Tables | 10 (`sbtest1` … `sbtest10`) |
| `--table-size` | 200000 |
| Engine | InnoDB |
| Size band | 400–700 MB (`data_length + index_length`) |

Prepare:

```bash
sysbench oltp_read_write \
  --db-driver=mysql \
  --mysql-host=lab-haproxy --mysql-port=3306 \
  --mysql-user=root --mysql-password=mysql \
  --mysql-db=sbtest --tables=10 --table-size=200000 \
  prepare
```

Sanity SQL:

```sql
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema='sbtest' AND table_name LIKE 'sbtest%';

SELECT ROUND(SUM(data_length+index_length)/1024/1024) AS size_mb
FROM information_schema.tables
WHERE table_schema='sbtest';

SELECT @@hostname, @@read_only, @@gtid_mode;
SELECT SERVICE_STATE FROM performance_schema.replication_connection_status;
SELECT SERVICE_STATE FROM performance_schema.replication_applier_status;
```

## Ports

| Service | Host | NodePort |
| --- | --- | --- |
| MySQL via HAProxy | 3307 | 30306 |
| Grafana | 3001 | 30300 |
| Prometheus | 9091 | 30091 |

## Measured row counts

From the 2026-09-10 lab run (`make load-data`, then `ANALYZE TABLE`):

| Check | Value |
| --- | --- |
| `sbtest` tables | 10 (`sbtest1` … `sbtest10`) |
| `COUNT(*)` `sbtest1` / `sbtest10` | 200000 / 200000 |
| `SUM(data_length+index_length)` | **471 MB** after load; **493 MB** after restore |
| Replica IO/SQL | `ON` / `ON` on each replica |
| Prometheus `up{job="mysql"}` | `1` on mysql-0, mysql-1, mysql-2 |

Failover: force-delete the current source pod, then Orchestrator `/api/recover`. The playbook requires a new writable source **and** the former source (or another replica) with `@@read_only=1` and replica IO/SQL `ON` against that source. See [blog-draft.md](blog-draft.md) for the measured after topology.

Backup: `s3://mysql-lab-backups/lab/lab-2026-09-10-19:19:11-full` state `Succeeded`.

Restore: post-backup canary table count 0; 10 sysbench tables remain.

Scale-out: `mysql.size` 2 → 3; `lab-mysql-2` has 10 tables and replica IO/SQL `ON`.
