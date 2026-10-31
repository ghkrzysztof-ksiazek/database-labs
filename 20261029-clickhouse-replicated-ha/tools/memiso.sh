#!/usr/bin/env bash
# Which half of the load makes the server's resident memory grow? Runs the loader
# as writer only, then reader only, and samples memory every 10 s.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
DUR=${1:-90}
q() { docker exec "$1" clickhouse-client --password chpass -q "$2" 2>&1 | head -1; }
for mode in ${MODES:-writer reader}; do
  ./scripts/lab.sh deploy >/dev/null 2>&1; docker rm -f loadgen >/dev/null
  case $mode in writer) sed 's/^writer & reader &$/writer \&/' scripts/load.sh > /tmp/load-$mode.sh;;
                reader) sed 's/^writer & reader &$/reader \&/' scripts/load.sh > /tmp/load-$mode.sh;; esac
  docker run -d --name loadgen --network ch-ha -v /tmp/load-$mode.sh:/load.sh:ro -v "$ROOT/out:/out" \
    --entrypoint bash clickhouse/clickhouse-server:25.8 /load.sh >/dev/null
  echo "== $mode only"
  for i in $(seq 0 10 $DUR); do
    for h in ch-1; do echo "$mode +${i}s $h rss=$(q $h "SELECT round(value/1048576) FROM system.asynchronous_metrics WHERE metric='MemoryResident'") alloc=$(q $h "SELECT round(value/1048576) FROM system.asynchronous_metrics WHERE metric='jemalloc.allocated'") tracked=$(q $h "SELECT round(value/1048576) FROM system.metrics WHERE metric='MemoryTracking'") outdated=$(q $h "SELECT value FROM system.metrics WHERE metric='PartsOutdated'") rows=$(q $h "SELECT count() FROM lab.events")"; done
    sleep 10
  done
  docker logs --tail 1 loadgen
  ./scripts/lab.sh teardown >/dev/null 2>&1
done
