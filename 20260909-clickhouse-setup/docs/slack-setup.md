# Slack Incoming Webhook for this lab

Alertmanager talks to Slack with an **Incoming Webhook**. That is a URL, not a bot token and not a Slack MCP login. Anyone who has the URL can post into the channel you selected.

## What to copy back into this repo

Put these three values in `ansible/inventory/group_vars/secrets.yml` (gitignored) or paste them in chat:

| Field | Example | Where it comes from |
| --- | --- | --- |
| `slack_webhook_url` | `https://hooks.slack.com/services/T…/B…/…` | Slack app → Incoming Webhooks |
| `slack_channel` | `#clickhouse-lab-alerts` | The channel you bound the webhook to |
| Workspace name | `my-team` | Slack workspace switcher (sanity check only) |

## Create the webhook (UI)

1. Open [https://api.slack.com/apps](https://api.slack.com/apps) while logged into the **same** workspace that should receive pages.
2. **Create New App** → **From scratch**.
3. App name: `clickhouse-lab` (any name is fine). Pick the workspace.
4. In the app sidebar: **Incoming Webhooks** → toggle **On**.
5. **Add New Webhook to Workspace**.
6. Choose a channel (create `#clickhouse-lab-alerts` first if you want a dedicated one).
7. **Allow**.
8. Copy **Webhook URL**. It always starts with `https://hooks.slack.com/services/`.

Org / Enterprise Grid workspaces may require an admin to approve the app before step 5 succeeds.

## Apply it to the cluster

```bash
cp ansible/inventory/group_vars/secrets.yml.example ansible/inventory/group_vars/secrets.yml
# edit the two Slack fields
./scripts/lab.sh configure-slack
./scripts/lab.sh test-alert
```

`configure-slack` Helm-upgrades Alertmanager with `global.slack_api_url` and a `slack` receiver. `test-alert` POSTs `ClickHouseLabTestAlert` to `http://127.0.0.1:9093/api/v2/alerts`. After `group_wait` (30s) you should see a message in the channel.

If the channel is wrong, Incoming Webhooks still post to the channel selected when the URL was created; the `slack_channel` field is mainly for the payload metadata Alertmanager sends.

## Rotate if it leaks

Slack app → Incoming Webhooks → delete the webhook → create a new one → update `secrets.yml` → `./scripts/lab.sh configure-slack`.
