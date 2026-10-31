#!/usr/bin/env bash
# Memory diagnosis: run the lab with the loader for N seconds and print, per server,
# what the server tracks (MemoryTracking), what the OS sees (MemoryResident) and the
# allocator's view (jemalloc.*), plus per-query peaks of the reader's GROUP BY.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
DUR=${1:-60}
q() { docker exec "$1" clickhouse-client --password chpass -q "$2" 2>&1; }
./scripts/lab.sh deploy >/dev/null 2>&1 || { echo deploy failed; exit 1; }
echo "cores: $(q ch-1 "SELECT value FROM system.asynchronous_metrics WHERE metric='NumberOfCPUCores'")  max_threads(app): $(docker exec ch-1 clickhouse-client --user app --password app -q "SELECT value FROM system.settings WHERE name='max_threads'")"
echo "time host tracked_MiB rss_MiB jemalloc_alloc_MiB jemalloc_resident_MiB jemalloc_retained_MiB pdirty_MiB markcache_MiB arenas threads"
end=$(( $(date +%s) + DUR ))
while [ "$(date +%s)" -lt "$end" ]; do
  for h in ch-1 ch-2; do
    r=$(q $h "SELECT
      round((SELECT value FROM system.metrics WHERE metric='MemoryTracking')/1048576),
      round(maxIf(value, metric='MemoryResident')/1048576),
      round(maxIf(value, metric='jemalloc.allocated')/1048576),
      round(maxIf(value, metric='jemalloc.resident')/1048576),
      round(maxIf(value, metric='jemalloc.retained')/1048576),
      round(maxIf(value, metric='jemalloc.arenas.all.pdirty')*4096/1048576),
      round(maxIf(value, metric='MarkCacheBytes')/1048576),
      maxIf(value, metric='jemalloc.arenas.all.narenas'),
      (SELECT value FROM system.metrics WHERE metric='GlobalThread')
      FROM system.asynchronous_metrics" | tr '\t' ' ')
    echo "$(date +%T) $h $r"
  done
  sleep 5
done
for h in ch-1 ch-2; do
  echo "$h reader query memory (MiB) p50/max, count, errors: $(q $h "SYSTEM FLUSH LOGS; SELECT round(quantile(0.5)(memory_usage)/1048576), round(max(memory_usage)/1048576), countIf(type='QueryFinish'), countIf(type!='QueryFinish') FROM system.query_log WHERE query LIKE 'SELECT user_id, count()%' AND type != 'QueryStart'" | tr '\t' ' ')"
done
echo "MEMORY_LIMIT_EXCEEDED in reader.err: $(grep -c MEMORY_LIMIT_EXCEEDED out/reader.err)"
docker logs --tail 2 loadgen
./scripts/lab.sh teardown >/dev/null 2>&1; echo torn-down
