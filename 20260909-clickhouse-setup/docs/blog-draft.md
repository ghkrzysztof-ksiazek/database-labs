# Draft: A ClickHouse cluster on a laptop, with Prometheus and Slack pages

*Working notes for a blog post. Commands and counts below were measured on the lab in this repo (kind + Ansible), not invented.*

## Hook

You can run a **two-replica ClickHouse cluster**, **three Keepers**, **Prometheus / Grafana / Alertmanager**, and (once you add a webhook) **Slack pages** on a single Docker host. The installer is Ansible; the source of truth at runtime is Kubernetes.

## What we deployed

- **kind** cluster `clickhouse-lab`: 1 control-plane + 2 workers
- **Altinity operator** Helm chart `0.27.3`
- **ClickHouse** `25.8`, 1 shard × 2 replicas, cluster secret for Distributed queries
- **ClickHouse Keeper** `25.8`, 3 nodes (24.8 crashed: operator injected `use_xid_64`)
- **NYC taxi** `trips_0.gz` from ClickHouse’s public documentation bucket
- **kube-prometheus-stack** `88.5.2`

Diagrams: [architecture.svg](diagrams/architecture.svg), [alerting.svg](diagrams/alerting.svg). Narrative: [how-it-works.md](how-it-works.md).

## One-liner path for the reader

```bash
./scripts/lab.sh bootstrap
./scripts/lab.sh deploy
./scripts/lab.sh load-data
./scripts/lab.sh verify
```

Give Docker about 8 GB RAM.

## Measured results (this laptop)

| Check | Result |
| --- | --- |
| `SELECT count() FROM nyc.trips` | **1,000,660** on **both** replicas |
| `SELECT count() FROM nyc.trips_dist` | **1,000,660** |
| Pickup years in the sample | **2015 only**, avg fare **13.20** |
| Prometheus `up{job="clickhouse-http"}` | **1** on both replicas |
| Prometheus `up{job="keeper-metrics"}` | **1** on three Keepers |
| Grafana dashboard | [ClickHouse lab](http://127.0.0.1:3000/d/clickhouse-lab/clickhouse-lab) (`admin` / `admin`) |
| Alertmanager | Ready; accepts `ClickHouseLabTestAlert` |

Lab HTTP: `http://127.0.0.1:8123` user `default` password `clickhouse`.

```sql
SELECT
    toYear(pickup_date) AS year,
    round(avg(fare_amount), 2) AS avg_fare,
    count() AS trips
FROM nyc.trips
GROUP BY year
ORDER BY year;
```

## Monitoring job names (easy to get wrong)

Prometheus Operator named the scrape jobs after the **Services**, not the ServiceMonitor object names:

- ClickHouse HTTP metrics → `job="clickhouse-http"`
- Keeper → `job="keeper-metrics"`

Alerts `ClickHouseDown` / `ClickHouseKeeperDown` must match those labels or they never fire.

## Slack

Incoming Webhook was applied via `ansible/inventory/group_vars/secrets.yml` (gitignored) and `./scripts/lab.sh configure-slack`. A direct webhook POST returned HTTP 200. `ClickHouseLabTestAlert` is active in Alertmanager with receiver `slack` (channel `#all-notifications`). Check that channel for the grouped message after `group_wait` (30s).

## Pitfalls worth a sidebar

- Ansible `group_vars` must sit next to the **inventory** (or the playbook), not in a random `ansible/group_vars/` folder.
- `kubernetes.core` needs the **venv** Python (`kubernetes` package), not Homebrew’s bare `python3`.
- Pin Keeper to a version that understands settings the operator writes (`use_xid_64` on 0.27.x).
- YAML `receiver: null` is a real null; name the silent receiver `noop`.
- Set a ClickHouse **cluster secret** or Distributed queries fail with `AUTHENTICATION_FAILED` between replicas.

## Teardown

```bash
./scripts/lab.sh teardown
```
