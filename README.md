# ClickHouse Kubernetes lab (localhost)

A blog-ready local lab: **kind** Kubernetes, a **replicated ClickHouse** cluster managed by the **Altinity operator**, **Ansible** as the installer, **NYC taxi** sample data, and **Prometheus / Alertmanager / Grafana** with Slack notifications.

This is a **test setup**. Passwords, open networks, and Slack webhooks are for a laptop lab, not production.

## What you get

| Piece | Choice |
| --- | --- |
| Local Kubernetes | [kind](https://kind.sigs.k8s.io/) (one control-plane + two workers) |
| ClickHouse | 1 shard × 2 replicas, image `clickhouse/clickhouse-server:25.8` |
| Coordination | 3-node ClickHouse Keeper |
| Operator | Altinity ClickHouse operator Helm chart `0.27.3` |
| Data | Public NYC taxi file `trips_0.gz` (~1M rows) from [ClickHouse’s documentation bucket](https://datasets-documentation.s3.eu-west-3.amazonaws.com/nyc-taxi/trips_0.gz) |
| Monitoring | kube-prometheus-stack (Prometheus, Alertmanager, Grafana) |
| Alerts | PrometheusRules → Alertmanager → Slack Incoming Webhook |

Step-by-step narrative, diagrams, and query examples: **[docs/how-it-works.md](docs/how-it-works.md)**. Table DDL, cluster layout, connection strings, and SQL: **[docs/cluster-and-data.md](docs/cluster-and-data.md)**. Publishable draft with measured numbers: **[docs/blog-draft.md](docs/blog-draft.md)**. Slack webhook walkthrough: **[docs/slack-setup.md](docs/slack-setup.md)**.

## Prerequisites

- Docker Desktop (or another Docker engine) with **~8 GB RAM** allocated
- macOS with Homebrew (the Ansible `prereqs` role installs `kind`, `kubectl`, and `helm`)
- Python 3.11+

## Quick start

If `make` works on your machine:

```bash
make bootstrap
make deploy
make load-data
make verify
```

If `make` is missing (or Xcode CLI tools are not installed), use the wrapper:

```bash
chmod +x scripts/lab.sh
./scripts/lab.sh bootstrap
./scripts/lab.sh deploy
./scripts/lab.sh load-data
./scripts/lab.sh verify
```

After deploy, from the host:

| Service | URL |
| --- | --- |
| ClickHouse HTTP | http://127.0.0.1:8123 |
| Grafana | http://127.0.0.1:3000 (admin / `admin`) — dashboard [ClickHouse lab](http://127.0.0.1:3000/d/clickhouse-lab/clickhouse-lab) |
| Prometheus | http://127.0.0.1:9090 |
| Alertmanager | http://127.0.0.1:9093 |

```bash
curl 'http://127.0.0.1:8123/?user=default&password=clickhouse' \
  --data-binary 'SELECT count() FROM nyc.trips_dist'
```

Kubeconfig is written to `.kube/config` (gitignored). Example:

```bash
export KUBECONFIG="$PWD/.kube/config"
kubectl get chi,chk,pods -n clickhouse
```

Tear down:

```bash
make teardown
```

## Slack alerts

Alertmanager is installed even without Slack. Until a webhook is configured, alerts stay inside Alertmanager.

**I need these three values from you** (paste them in chat or into `ansible/inventory/group_vars/secrets.yml`):

1. **Incoming Webhook URL** — `https://hooks.slack.com/services/...`
2. **Channel** — for example `#clickhouse-lab-alerts`
3. **Workspace** — only so we can sanity-check the webhook belongs to the channel you expect

### Where to get the webhook

1. Open [https://api.slack.com/apps](https://api.slack.com/apps) while logged into the Slack workspace that should receive alerts.
2. **Create New App** → **From scratch** → name it e.g. `clickhouse-lab` → pick the workspace.
3. In the app: **Incoming Webhooks** → **On**.
4. **Add New Webhook to Workspace** → select the channel → **Allow**.
5. Copy **Webhook URL**. Treat it like a password (anyone with it can post to that channel).

If your org uses Slack Enterprise Grid, an admin may have to approve the app.

Then:

```bash
cp ansible/inventory/group_vars/secrets.yml.example ansible/inventory/group_vars/secrets.yml
# edit slack_webhook_url and slack_channel
./scripts/lab.sh configure-slack
./scripts/lab.sh test-alert
```

`configure-slack` upgrades Alertmanager via Helm. `test-alert` posts a synthetic firing alert. You should see it in Slack within about a minute (`group_wait` is 30s).

## Layout

```
ansible/                 # installer
  playbooks/site.yml     # kind + operator + cluster + monitoring
  playbooks/load-data.yml
  playbooks/verify.yml
  playbooks/test-alert.yml
  playbooks/teardown.yml
  roles/
k8s/                     # rendered manifests (created on deploy)
docs/how-it-works.md     # blog-style walkthrough + diagrams
```

## Defaults (lab only)

- ClickHouse user `default` / password `clickhouse`
- Grafana `admin` / `admin`
- Networks for the ClickHouse user: `0.0.0.0/0` (cluster-internal plus kind NodePorts)
