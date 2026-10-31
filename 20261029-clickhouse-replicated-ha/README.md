# ClickHouse replicated HA lab

Two ClickHouse 25.8 replicas, a three-node ClickHouse Keeper ensemble and HAProxy on Docker Compose, with a load generator, so you can kill a replica, the Keeper leader or the Keeper majority under load and watch what the application sees.

The write-up is a blog series: see the posts at <https://db-ex.eu/blog/>.

## Prerequisites

- macOS with Docker Desktop (Docker Engine and the `docker compose` plugin). Tested on macOS 27.0.1 (Apple silicon) with Docker Desktop 29.7.2 and Compose 5.4.0.
- Memory: the test runs used a Docker VM with 12 CPUs and 15.6 GiB. Each ClickHouse server is capped at 4 GB (`max_server_memory_usage` in `cluster.xml`); peak resident memory per server in the full runs was 2,142–2,813 MiB. Give Docker at least 8 GB.
- Disk: about 1.7 GB for the three images (`clickhouse/clickhouse-server:25.8`, `clickhouse/clickhouse-keeper:25.8`, `haproxy:3.2`), plus the data volumes.
- `bash`, `curl` and `perl` (used by `tools/run-experiments.sh`). `python3` for `tools/analyse.py` and the tests. Google Chrome or Chromium only if you want HAProxy stats screenshots.

## Layout

```text
loadgen ──> haproxy ──> ch-1, ch-2         (ReplicatedMergeTree table lab.events, cluster "lab", 1 shard x 2 replicas)
                        └── keeper-1, keeper-2, keeper-3   (Raft ensemble, port 9181 inside the network)
```

All containers are on the Docker network `ch-ha`. Ports published on the host (all bound to `127.0.0.1`):

| What | Host port | Login |
|---|---|---|
| HAProxy, ClickHouse native protocol | `19000` | `app` / `app` |
| HAProxy, ClickHouse HTTP | `18123` | `app` / `app` |
| HAProxy stats page | `18404` (`http://127.0.0.1:18404/`) | none |
| ch-1 HTTP / native | `18124` / `19001` | `default` / `chpass` |
| ch-2 HTTP / native | `18125` / `19002` | `default` / `chpass` |
| keeper-1, keeper-2, keeper-3 | `19181`, `19182`, `19183` | none |

`app` can only `SELECT` and `INSERT` on `lab.*`. HAProxy health-checks each server with `GET /replicas_status` on port 8123 (`inter 1s fall 2 rise 2`). The Keeper session timeout is 30 s. Passwords are plain text and there is no TLS: this is a laptop lab, not a production config.

## Quick start

```bash
./scripts/lab.sh deploy     # pull images, start the 6 containers, create lab.events, load 1,000,000 seed rows, start loadgen
./scripts/lab.sh verify     # prints "verify: steady state ok (...)" or "verify: FAILED - <reason>"
docker logs -f loadgen      # one line per second: inserts/s, ins_err/s, selects/s, sel_err/s
./scripts/lab.sh teardown   # remove loadgen, the containers, volumes and the ch-ha network
```

`make deploy`, `make verify` and `make teardown` do the same. `verify` is safe to run while the load generator is writing; it fails after an experiment if something is still down.

### Run the experiments

All four experiments (A: kill a replica; B: kill the Keeper leader; C: kill a second Keeper; D: `insert_quorum`, unknown status and a deduplicated retry), the no-loss check and teardown run from one script. It does its own deploy and teardown, so start from no lab or from a lab you don't mind losing:

```bash
./tools/run-experiments.sh <label>                                   # outputs go to results/<label>/ (replaced if it exists)
SHOT_CMD="$PWD/tools/shot-haproxy.sh" ./tools/run-experiments.sh <label>   # also save HAProxy stats screenshots
python3 tools/analyse.py results/<label>                             # summarise a run as JSON
```

A full run takes about nine minutes; experiment C alone waits close to five.

Memory diagnostics (each deploys the lab and tears it down at the end):

```bash
./tools/memdiag.sh [seconds]                 # default 60: tracked vs resident vs jemalloc memory every 5 s, reader query peaks
MODES="writer reader" ./tools/memiso.sh [seconds]   # default 90: writer-only, then reader-only load, memory every 10 s
```

## Files

| Path | What it is |
|---|---|
| `docker/docker-compose.yml` | The six services (`keeper-1..3`, `ch-1`, `ch-2`, `haproxy`), the `ch-ha` network and five volumes |
| `docker/keeper/keeper-{1,2,3}.xml` | Keeper configs: Raft members, port 9181, 30 s session timeout |
| `docker/clickhouse/config.d/cluster.xml` | Shared server config: Keeper nodes, cluster `lab`, 4 GB memory cap, 10 s `old_parts_lifetime` |
| `docker/clickhouse/macros/ch-{1,2}.xml` | Per-server `{shard}` / `{replica}` macros |
| `docker/clickhouse/users.d/app.xml` | The `app` user |
| `docker/clickhouse/schema.sql` | `lab` database and the `lab.events` ReplicatedMergeTree table, `ON CLUSTER lab` |
| `docker/haproxy/haproxy.cfg` | Native and HTTP frontends, `/replicas_status` checks, stats page |
| `Makefile` | `make deploy`, `make verify`, `make teardown`, calling `scripts/lab.sh` |
| `scripts/lab.sh` | Entry point: `deploy`, `verify`, `teardown` |
| `scripts/deploy.sh` | Builds the lab from an empty Docker state and starts `loadgen` |
| `scripts/verify.sh` | Healthy-state check: 1 Keeper leader + 2 followers; both replicas writable, seeing 2 active replicas, under 10 s behind; 1,000,000 seed rows each; both servers UP in HAProxy's native backend |
| `scripts/load.sh` | The load generator (runs in the `loadgen` container): one writer of 1,000-row inserts, one `GROUP BY` reader, acknowledged batches in `out/acked.txt` |
| `scripts/teardown.sh` | Removes `loadgen`, the Compose project with its volumes, and the loader's files in `out/` |
| `tools/run-experiments.sh` | Deploy, verify, experiments A–D, no-loss check, teardown; keeps every output in `results/<label>/` |
| `tools/analyse.py` | Summarises one or more `results/<label>/` folders as JSON |
| `tools/memdiag.sh` | Memory diagnosis under load |
| `tools/memiso.sh` | Memory under writer-only, then reader-only load |
| `tools/shot-haproxy.sh` | Headless-Chrome screenshot of the HAProxy stats page, used through `SHOT_CMD` |
| `docs/manual-setup.md` | The build typed out one command at a time, with what you should see (fixed sleeps where `deploy.sh` polls) |
| `tests/test_lab_layout.py` | Consistency checks: `python3 -m unittest discover -s tests` |
| `screenshots/` | Figures and screenshots used in the posts |
| `out/`, `results/` | Run output (git-ignored) |
