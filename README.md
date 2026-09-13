# database-labs

Reproducible database lab environments that run on a single laptop.

Each lab builds a real cluster inside [kind](https://kind.sigs.k8s.io/) (Kubernetes
nodes as Docker containers), installs it with Ansible, loads a realistic dataset,
and wires up Prometheus and Grafana. Every one can be created and destroyed with a
single command, which is the point: these exist so you can break things on purpose
and rebuild in minutes.

Each experiment lives in its own dated directory (`YYYYMMDD-name`).

| Directory | What it is | Write-up |
| --- | --- | --- |
| [20260909-clickhouse-setup](20260909-clickhouse-setup/) | Replicated ClickHouse cluster (1 shard × 2 replicas) with a 3-node Keeper ensemble, the Altinity operator, NYC taxi sample data, and Prometheus alerts routed to Slack | [ClickHouse – a replicated cluster on your laptop with kind and Ansible](https://db-ex.eu/blog/clickhouse-a-replicated-cluster-on-your-laptop-with-kind-and-ansible/) |
| [20260910-mysql-replication-setup](20260910-mysql-replication-setup/) | MySQL source–replica cluster on the Percona ps-operator: async GTID replication, Orchestrator failover, XtraBackup to in-cluster MinIO, canary-verified restore, and scale-out | [MySQL – a replication lab with failover, backups, and scale-out on Kubernetes](https://db-ex.eu/blog/mysql-replication-lab-failover-backups-and-scale-out-on-kubernetes/) |
| [20260911-mysql-replication-backups](20260911-mysql-replication-backups/) | MySQL backup verification lab: XtraBackup full/incremental/replica-sourced backups to MinIO, scheduled backups and retention, in-place restore, point-in-time recovery to a timestamp and to a GTID, and a restore into a separate cluster that attaches as a replica and catches up | [MySQL – test your backup by restoring it as a replica](https://db-ex.eu/blog/mysql-test-your-backup-by-restoring-it-as-a-replica/) |

## Running a lab

Each directory is self-contained. From inside one:

```bash
./scripts/lab.sh bootstrap    # install kind, kubectl, helm; check Docker
./scripts/lab.sh deploy       # create the cluster and everything in it
./scripts/lab.sh load-data    # load the sample dataset
./scripts/lab.sh verify       # assert the cluster is in the expected state
./scripts/lab.sh teardown     # delete the kind cluster
```

`make bootstrap`, `make deploy` and so on work identically if `make` is available.
Individual labs add their own targets — see each README.

`bootstrap` creates a Python virtualenv and installs Ansible plus the
`kubernetes.core` collection. The `kubernetes` Python package must come from that
virtualenv, not from a system Python, or the Kubernetes modules fail to import.

## Requirements

- Docker Desktop (or another Docker engine) with about **8 GB RAM** and 4 CPUs
- macOS with Homebrew — the Ansible `prereqs` role installs `kind`, `kubectl`, and `helm`
- Python 3.11+

Labs pick non-overlapping host ports so more than one can run at a time.

## These are labs, not production

Every lab here uses plain-text passwords, permissive network settings, no TLS,
unsafe member counts, and local storage on a single Docker host. They reproduce
the operational *shape* of a production system — replication topology, failover,
backup and restore, metrics and alerting — so those paths are cheap to practise.
Do not copy the configuration into a real environment.

Secrets (Slack webhooks and similar) are read from gitignored files. Each lab
ships a `secrets.yml.example` showing the expected keys.
