# MySQL backup verification lab (localhost)

Measured validation: **12/12 scenarios passed** — [ordered run report](docs/results/20260912T101400Z-validation-run.md).

A blog-ready local lab that asks one question and answers it with evidence: **is this backup actually any good?**

**kind** Kubernetes, a source–replica **Percona Server 8.4** cluster run by the **Percona Operator for MySQL** `1.2.0`, **XtraBackup** to in-cluster **MinIO**, a **binlog server** streaming binary logs for point-in-time recovery, and twelve Ansible-driven scenarios that create backups, restore them, recover to a point in time — and finally restore into a *separate* cluster, attach it as a replica of the live one, and watch it catch up.

That last one is the point. A green backup job does not prove recoverability. A backup is verified when it has been restored and the restored copy has been shown to be a consistent, usable database.

This is a **test setup**. Passwords and open networks are for a laptop lab, not production.

## What you get

| Piece | Choice |
| --- | --- |
| Local Kubernetes | [kind](https://kind.sigs.k8s.io/) (one control-plane + two workers) |
| MySQL | Percona Server 8.4, async GTID replication, 1 source + 1 replica |
| Operator | Percona Operator for MySQL (ps-operator) Helm chart `1.2.0` |
| Backups | Percona XtraBackup — on demand, scheduled, full, incremental, and sourced from the replica |
| PITR | Binlog server `1.2.0-binlog-server-0.4.1` streaming to MinIO, recovery by timestamp or GTID |
| Object storage | In-cluster MinIO — `mysql-lab-backups` and `mysql-lab-binlogs` |
| Failover | Orchestrator (present, not the subject of this lab) |
| Data | sysbench `oltp_read_write` prepare, **10 tables**, about **500 MB** |
| Monitoring | kube-prometheus-stack + mysqld_exporter sidecar |

How it all works, with diagrams: **[docs/backup-architecture.md](docs/backup-architecture.md)**.
What each scenario proves and how to run it alone: **[docs/test-catalogue.md](docs/test-catalogue.md)**.
Measured runs, generated not written: **[docs/results/](docs/results/)**.
The publishable narrative: **[docs/blog-draft.md](docs/blog-draft.md)**. Published: **[MySQL – test your backup by restoring it as a replica](https://db-ex.eu/blog/mysql-test-your-backup-by-restoring-it-as-a-replica/)**.

Run commands from this directory (`20260911-mysql-replication-backups/`).

## Prerequisites

- Docker Desktop (or another Docker engine) with **~8 GB RAM** allocated
- macOS with Homebrew (the Ansible `prereqs` role installs `kind`, `kubectl`, and `helm`)
- Python 3.11+

## Quick start

```bash
./scripts/lab.sh bootstrap
./scripts/lab.sh deploy
./scripts/lab.sh load-data
./scripts/lab.sh verify
./scripts/lab.sh test-backups
```

`make` targets exist for the same commands (`make deploy`, `make test-backups`, …) if `make` is installed.

First deploy pulls Percona, MinIO and kube-prometheus images. The full scenario suite takes a couple of hours, most of it spent restoring.

After deploy, from the host:

| Service | URL |
| --- | --- |
| MySQL (HAProxy primary) | `127.0.0.1:3307` user `root` / password `mysql` |
| Grafana | http://127.0.0.1:3001 (`admin` / `admin`) |
| Prometheus | http://127.0.0.1:9091 |

Kubeconfig is written to `.kube/config` (gitignored):

```bash
export KUBECONFIG="$PWD/.kube/config"
kubectl get ps,pods -n mysql
```

## The twelve scenarios

| # | Scenario | Group |
| --- | --- | --- |
| t01 | On-demand full backup to MinIO | backups are produced |
| t02 | Backup taken from the replica, primary untouched | backups are produced |
| t03 | Incremental backup on a full base | backups are produced |
| t04 | Backup and binlog objects present in MinIO | backups are produced |
| t05 | Scheduled backup runs unattended | backups are produced |
| t06 | Retention prunes scheduled backups down to keep | backups are produced |
| t07 | Whole-cluster restore rolls back post-backup writes | backups restore |
| t08 | Restore recovers a dropped table | backups restore |
| t09 | Point-in-time recovery to a timestamp | backups restore |
| t10 | Point-in-time recovery to a GTID | backups restore |
| t11 | An impossible recovery target fails cleanly | backups restore |
| **t12** | **Restore into a new cluster, attach as a replica, catch up** | **backups are usable** |

Run one on its own with `./scripts/lab.sh t09`. Every scenario records its verdict, duration and raw command output to `docs/results/<run_id>.jsonl`, rendered into `docs/results/<run_id>-run.md`.

## Operations

```bash
./scripts/lab.sh backup        # on-demand XtraBackup to MinIO
./scripts/lab.sh restore       # whole-cluster restore, canary-verified
./scripts/lab.sh test-backups  # the full twelve-scenario suite + report
./scripts/lab.sh test          # offline structural tests of the shipped templates
./scripts/lab.sh teardown
```

## Layout

```
ansible/
  playbooks/site.yml           # kind + operator + minio + cluster + monitoring
  playbooks/load-data.yml
  playbooks/verify.yml
  playbooks/backup.yml
  playbooks/restore.yml
  playbooks/tests/             # one playbook per scenario, plus all.yml
  roles/
    test_common/               # health gate, result recording, mc helper
    test_report/               # renders the run report
    t01_… t12_…                # one role per scenario
k8s/                           # rendered manifests (created on deploy)
docs/backup-architecture.md
docs/test-catalogue.md
docs/results/                  # measured runs
tests/test_lab_config.py       # offline structural tests
```

## Defaults (lab only)

- MySQL `root` / `mysql`
- Grafana `admin` / `admin`
- MinIO `minio` / `minio12345`
