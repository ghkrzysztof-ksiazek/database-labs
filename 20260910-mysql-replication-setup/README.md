# MySQL replication Kubernetes lab (localhost)

A blog-ready local lab: **kind** Kubernetes, a **source–replica MySQL** cluster managed by the **Percona Operator for MySQL**, **Ansible** as the installer, **sysbench** sample data (~500MB, 10 tables), **XtraBackup** to in-cluster MinIO, **Orchestrator** automated failover, and **Prometheus / Grafana**.

This is a **test setup**. Passwords and open networks are for a laptop lab, not production.

## What you get

| Piece | Choice |
| --- | --- |
| Local Kubernetes | [kind](https://kind.sigs.k8s.io/) (one control-plane + two workers) |
| MySQL | Percona Server 8.4, async GTID replication, 1 source + 1 replica (scale-out adds a second replica) |
| Failover | Orchestrator (automatic primary election) |
| Operator | Percona Operator for MySQL (ps-operator) Helm chart `1.2.0` |
| Data | sysbench `oltp_read_write` prepare, **10 tables**, about **500MB** |
| Backups | Percona XtraBackup on a schedule, stored in in-cluster MinIO |
| Monitoring | kube-prometheus-stack + mysqld_exporter sidecar |

Step-by-step narrative and diagrams: **[docs/how-it-works.md](docs/how-it-works.md)**. Cluster layout and SQL: **[docs/cluster-and-data.md](docs/cluster-and-data.md)**. Publishable draft with measured failover / backup / scale-out: **[docs/blog-draft.md](docs/blog-draft.md)**.

Run commands from this directory (`20260910-mysql-replication-setup/`).

## Prerequisites

- Docker Desktop (or another Docker engine) with **~8 GB RAM** allocated
- macOS with Homebrew (the Ansible `prereqs` role installs `kind`, `kubectl`, and `helm`)
- Python 3.11+

## Quick start

```bash
make bootstrap
make deploy
make load-data
make verify
```

Without `make`:

```bash
chmod +x scripts/lab.sh
./scripts/lab.sh bootstrap
./scripts/lab.sh deploy
./scripts/lab.sh load-data
./scripts/lab.sh verify
```

Give Docker about 8 GB RAM. First deploy pulls Percona, MinIO, and kube-prometheus images.

After deploy, from the host:

| Service | URL |
| --- | --- |
| MySQL (HAProxy primary) | `127.0.0.1:3307` user `root` / password `mysql` |
| Grafana | http://127.0.0.1:3001 (`admin` / `admin`) — dashboard [MySQL replication lab](http://127.0.0.1:3001/d/mysql-lab/mysql-replication-lab) |
| Prometheus | http://127.0.0.1:9091 |

Kubeconfig is written to `.kube/config` (gitignored):

```bash
export KUBECONFIG="$PWD/.kube/config"
kubectl get ps,pods -n mysql
```

## Operations paths

```bash
make failover     # force-delete the source pod; Orchestrator promotes a replica; old source rejoins
make backup       # on-demand XtraBackup to MinIO
make restore      # whole-cluster restore; a post-backup canary must disappear
make scale-out    # mysql.size 2 → 3; new replica catches up
make teardown
```

## Layout

```
ansible/                 # installer
  playbooks/site.yml     # kind + operator + minio + cluster + monitoring
  playbooks/load-data.yml
  playbooks/verify.yml
  playbooks/failover.yml
  playbooks/backup.yml
  playbooks/restore.yml
  playbooks/scale-out.yml
  playbooks/teardown.yml
  roles/
k8s/                     # rendered manifests (created on deploy)
docs/how-it-works.md
tests/test_lab_config.py # structural tests of shipped templates
```

## Defaults (lab only)

- MySQL `root` / `mysql`
- Grafana `admin` / `admin`
- MinIO `minio` / `minio12345`
