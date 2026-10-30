#!/usr/bin/env bash
# Build the lab from an empty Docker state. Every step is also written out in
# docs/manual-setup.md; keep the two in lockstep.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f "$ROOT/docker/docker-compose.yml")
q() { docker exec "$1" clickhouse-client --password chpass -q "$2"; }

# Docker 29 on a host without systemd can program nftables while leaving
# iptables-legacy FORWARD policy DROP. Containers on the lab bridge then
# resolve each other but cannot connect. A normal engine is not modified.
# Docker Desktop on macOS has no iptables-legacy, so this is skipped there.
if command -v iptables-legacy >/dev/null 2>&1 && sudo -n iptables-legacy -S FORWARD 2>/dev/null | head -n 1 | grep -q -- '-P FORWARD DROP'; then
    echo "== iptables-legacy FORWARD policy is DROP; setting ACCEPT so containers can reach each other =="
    sudo iptables-legacy -P FORWARD ACCEPT
fi

echo "== pull images =="
"${COMPOSE[@]}" pull -q

echo "== remove any previous lab =="
docker rm -f loadgen >/dev/null 2>&1 || true
"${COMPOSE[@]}" down -v --remove-orphans

echo "== start three Keepers, two ClickHouse servers, HAProxy =="
"${COMPOSE[@]}" up -d
for i in $(seq 1 120); do
    if q ch-1 "SELECT 1" >/dev/null 2>&1 && q ch-2 "SELECT 1" >/dev/null 2>&1; then break; fi
    [ "$i" -eq 120 ] && { echo "timed out waiting for ch-1 / ch-2" >&2; exit 1; }
    sleep 1
done
echo "ch-1 and ch-2 answer queries"

echo "== wait for a Keeper leader =="
for i in $(seq 1 60); do
    if q ch-1 "SELECT count() FROM system.zookeeper WHERE path = '/'" >/dev/null 2>&1; then break; fi
    [ "$i" -eq 60 ] && { echo "timed out waiting for Keeper" >&2; exit 1; }
    sleep 1
done

echo "== database and replicated table =="
docker exec -i ch-1 clickhouse-client --password chpass --multiquery < docker/clickhouse/schema.sql

echo "== a million rows with known dimensions =="
q ch-1 "
  INSERT INTO lab.events
  SELECT now64(3) - toIntervalSecond(number % 86400), 0, number,
         number % 10000, (number % 1000) / 10
  FROM numbers(1000000)"
for i in $(seq 1 60); do
    [ "$(q ch-2 "SELECT count() FROM lab.events")" = 1000000 ] && break
    [ "$i" -eq 60 ] && { echo "ch-2 did not reach 1000000 rows" >&2; exit 1; }
    sleep 1
done

echo "== wait for HAProxy to mark both servers UP =="
for i in $(seq 1 30); do
    up=$(curl -s "http://127.0.0.1:18404/;csv" | awk -F, '$1=="ch_native" && $2 ~ /^ch-/ && $18=="UP"' | wc -l)
    [ "$up" -eq 2 ] && break
    [ "$i" -eq 30 ] && { echo "HAProxy has $up of 2 servers UP" >&2; exit 1; }
    sleep 1
done

echo "== start the load generator =="
mkdir -p out
docker run -d --name loadgen --network ch-ha \
  -v "$ROOT/scripts/load.sh:/load.sh:ro" -v "$ROOT/out:/out" \
  --entrypoint bash clickhouse/clickhouse-server:25.8 /load.sh >/dev/null
sleep 5
docker logs --tail 3 loadgen

echo "deploy: done. Run ./scripts/lab.sh verify"
