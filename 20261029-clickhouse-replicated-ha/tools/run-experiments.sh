#!/usr/bin/env bash
# Runs the whole post end to end and keeps every output: deploy, verify,
# experiments A-D, the no-loss check by batch list, teardown.
# Usage: ./tools/run-experiments.sh <label>     (results go to results/<label>/)
# Works with the bash 3.2 that ships with macOS.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
LABEL=${1:-run}; R="$ROOT/results/$LABEL"; rm -rf "$R"; mkdir -p "$R"
now() { perl -MTime::HiRes=time -MPOSIX=strftime -e '$t=time; printf "%s.%03d", strftime("%H:%M:%S", localtime($t)), ($t-int($t))*1000'; }
epoch() { perl -MTime::HiRes=time -e 'printf "%.3f", time'; }
ev() { echo "$(now) $*" | tee -a "$R/events.log"; }
q() { docker exec "$1" clickhouse-client --password chpass -q "$2" 2>&1; }
timed() { local t0 t1 out; t0=$(epoch); out=$(q "$1" "$2" | head -c 300 | tr '\n' ' '); t1=$(epoch); echo "$(perl -e "printf '%.3f', $t1-$t0") ${out:-ok}"; }
mntr() { for k in keeper-1 keeper-2 keeper-3; do
  s=$(docker exec $k bash -c 'exec 3<>/dev/tcp/127.0.0.1/9181; echo mntr >&3; cat <&3' 2>/dev/null | awk '$1=="zk_server_state"{print $2}')
  echo -n "$k=${s:-down} "; done; echo; }
leader() { mntr | tr ' ' '\n' | awk -F= '$2=="leader"{print $1}'; }
hap() { curl -s "http://127.0.0.1:18404/;csv" | awk -F, '$1=="ch_native" && $2 ~ /^ch-/ {printf "%s=%s ", $2, $18}'; echo; }
shot() { [ -n "${SHOT_CMD:-}" ] && "$SHOT_CMD" "$R/haproxy-$1.png" >/dev/null 2>&1; true; }
wait_q() { until q "$1" "SELECT 1" >/dev/null 2>&1; do sleep 0.5; done; }

ev "host: $(uname -sm) docker $(docker version --format '{{.Server.Version}}') $(docker info --format 'CPUs={{.NCPU}} Mem={{.MemTotal}}')"
ev "deploy start"; ./scripts/lab.sh deploy > "$R/deploy.log" 2>&1; ev "deploy end rc=$?"
# memory and parts sampler, every 2 s
( while [ ! -f "$R/.stop" ]; do for h in ch-1 ch-2; do
    m=$(docker exec $h clickhouse-client --password chpass -q "SELECT
      round((SELECT value FROM system.asynchronous_metrics WHERE metric='MemoryResident')/1048576),
      round((SELECT value FROM system.metrics WHERE metric='MemoryTracking')/1048576),
      (SELECT value FROM system.metrics WHERE metric='PartsOutdated')" 2>/dev/null | tr '\t' ' ')
    [ -n "$m" ] && echo "$(date +%T) $h $m" >> "$R/mem.txt"; done; sleep 2; done ) &
SAMPLER=$!
sleep 20
ev "verify: $(./scripts/lab.sh verify 2>&1)"
mntr > "$R/healthy-mntr.txt"
q ch-1 "SELECT cluster, shard_num, replica_num, host_name, port FROM system.clusters WHERE cluster = 'lab' FORMAT PrettyCompactMonoBlock" > "$R/healthy-clusters.txt"
q ch-2 "SELECT replica_name, is_leader, is_readonly, absolute_delay, queue_size, active_replicas, total_replicas FROM system.replicas WHERE table = 'events' FORMAT Vertical" > "$R/healthy-replicas.txt"
shot healthy

# ---- A: a replica dies
ev "A kill ch-1"; docker kill ch-1 >/dev/null
for i in $(seq 1 8); do echo "$(date +%T) $(hap)" >> "$R/A-haproxy.txt"; [ "$i" = 5 ] && shot A-ch1-down; sleep 1; done
q ch-2 "SELECT replica_name, is_readonly, active_replicas, total_replicas, queue_size FROM system.replicas WHERE table='events' FORMAT PrettyCompactMonoBlock" > "$R/A-replicas.txt"
sleep 25
q ch-2 "SELECT replica_name, is_readonly, active_replicas, total_replicas, queue_size FROM system.replicas WHERE table='events' FORMAT PrettyCompactMonoBlock" > "$R/A-replicas-35s.txt"
ev "A start ch-1"; docker start ch-1 >/dev/null; wait_q ch-1; ev "A ch-1 answers"
for i in $(seq 1 10); do echo "$(date +%T) $(hap)" >> "$R/A-haproxy-back.txt"; sleep 1; done
sleep 10

# ---- B: the Keeper leader dies
L1=$(leader); echo "before: $(mntr)" > "$R/B-mntr.txt"
for h in ch-1 ch-2; do echo "$h keeper session on: $(q $h "SELECT host FROM system.zookeeper_connection")"; done > "$R/B-sessions.txt"
ev "B kill leader $L1"; docker kill "$L1" >/dev/null
for i in 1 2 3 4 5; do sleep 1; echo "$(date +%T) $(mntr)" >> "$R/B-mntr.txt"; done
sleep 10

# ---- C: Keeper loses its majority
for h in ch-1 ch-2; do echo "$h keeper session on: $(q $h "SELECT host FROM system.zookeeper_connection")"; done > "$R/C-sessions-before.txt"
L2=$(leader); ev "C kill leader $L2 ($L1 still down)"; docker kill "$L2" >/dev/null; CK=$(date +%s)
sleep 40
for h in ch-1 ch-2; do q $h "SELECT '$h', is_readonly, is_session_expired, active_replicas FROM system.replicas WHERE table='events'"; done > "$R/C-state.txt"
curl -s -w ' http=%{http_code}\n' http://127.0.0.1:18124/replicas_status >> "$R/C-state.txt"; hap >> "$R/C-state.txt"; shot C-readonly
while [ "$(grep -c TABLE_IS_READ_ONLY out/writer.err 2>/dev/null)" -lt 2 ] && [ $(( $(date +%s) - CK )) -lt 330 ]; do sleep 1; done
ev "C read-only insert errors so far: $(grep -c TABLE_IS_READ_ONLY out/writer.err)"
ev "C insert with insert_keeper_max_retries=0: $(timed ch-1 "INSERT INTO lab.events SETTINGS insert_keeper_max_retries = 0 SELECT now64(3), 0, 1, 1, 1")"
ev "C start $L2"; docker start "$L2" >/dev/null
for i in $(seq 1 40); do
  s="$(date +%T)"; for h in ch-1 ch-2; do s="$s $h ro=$(q $h "SELECT is_readonly FROM system.replicas WHERE table='events'")"; done
  echo "$s" >> "$R/C-back.txt"; case "$s" in *"ch-1 ro=0 ch-2 ro=0"*) break;; esac; sleep 1; done
ev "C writable: $(tail -1 "$R/C-back.txt")"
sleep 10

# ---- D: insert_quorum
ev "D start $L1"; docker start "$L1" >/dev/null
for i in $(seq 1 30); do m=$(mntr); case "$m" in *down*) sleep 1;; *) break;; esac; done; ev "D keeper: $m"
QI="INSERT INTO lab.events SETTINGS insert_quorum = 2, insert_quorum_timeout = 5000 SELECT now64(3)"
ev "D healthy quorum insert 900001: $(timed ch-1 "$QI, 900001, number, 1, 1 FROM numbers(10)")"
ev "D kill ch-2"; docker kill ch-2 >/dev/null; sleep 1
ev "D quorum insert 900002, 1 s after kill: $(timed ch-1 "$QI, 900002, number, 1, 1 FROM numbers(10)")"
sleep 35
ev "D quorum insert 900003, after session expiry: $(timed ch-1 "$QI, 900003, number, 1, 1 FROM numbers(10)")"
ev "D start ch-2"; docker start ch-2 >/dev/null; wait_q ch-2; sleep 10
QF="INSERT INTO lab.events SETTINGS insert_quorum = 2, insert_quorum_timeout = 5000 SELECT toDateTime64('2026-10-29 23:00:00.000', 3), 900010, number, 1, 1 FROM numbers(10)"
ev "D dedup: kill ch-2"; docker kill ch-2 >/dev/null; sleep 1
ev "D dedup first insert: $(timed ch-1 "$QF")"
docker start ch-2 >/dev/null; wait_q ch-2; sleep 5
ev "D dedup retry: $(timed ch-1 "$QF")"
sleep 20

# ---- no-loss check, by batch list
ev "final: stop loadgen"; docker stop loadgen >/dev/null
sleep 5
for h in ch-1 ch-2; do
  q $h "SELECT DISTINCT batch FROM lab.events WHERE batch BETWEEN 1 AND 899999" | LC_ALL=C sort > "$R/batches-$h.txt"
  echo "$h: $(q $h "SELECT count(), uniqExact(batch), sum(cityHash64(ts, batch, id, user_id, value)) FROM lab.events" | tr '\t' ' ')" >> "$R/final.txt"
  echo "$h quorum/dedup batches: $(q $h "SELECT groupArray((batch, c)) FROM (SELECT batch, count() c FROM lab.events WHERE batch >= 900000 GROUP BY batch ORDER BY batch)")" >> "$R/final.txt"
  echo "$h loader batches without exactly 1000 rows: $(q $h "SELECT count() FROM (SELECT batch FROM lab.events WHERE batch BETWEEN 1 AND 899999 GROUP BY batch HAVING count() != 1000)")" >> "$R/final.txt"
done
# comm needs plain (byte-order) sorting, not numeric
LC_ALL=C sort out/acked.txt > "$R/acked-sorted.txt"
{
  echo "acked: $(wc -l < "$R/acked-sorted.txt")  ch-1 batches: $(wc -l < "$R/batches-ch-1.txt")  ch-2 batches: $(wc -l < "$R/batches-ch-2.txt")  highest batch sent: $(q ch-2 "SELECT max(batch) FROM lab.events WHERE batch < 900000")"
  echo "in ch-1 not ch-2: $(comm -23 "$R/batches-ch-1.txt" "$R/batches-ch-2.txt" | wc -l)   in ch-2 not ch-1: $(comm -13 "$R/batches-ch-1.txt" "$R/batches-ch-2.txt" | wc -l)"
  echo "acked but missing on ch-2: $(comm -23 "$R/acked-sorted.txt" "$R/batches-ch-2.txt" | wc -l)   on ch-2 but not acked: $(comm -13 "$R/acked-sorted.txt" "$R/batches-ch-2.txt" | tr '\n' ' ')"
  echo "MEMORY_LIMIT_EXCEEDED: reader $(grep -c MEMORY_LIMIT_EXCEEDED out/reader.err)  writer $(grep -c MEMORY_LIMIT_EXCEEDED out/writer.err)"
  echo "writer errors by code: $(grep -o 'Code: [0-9]*' out/writer.err | sort | uniq -c | tr '\n' ';')"
  echo "reader errors by code: $(grep -o 'Code: [0-9]*' out/reader.err | sort | uniq -c | tr '\n' ';')"
} | tee -a "$R/final.txt"
for h in ch-1 ch-2; do echo "$h reader query MiB p50/p99/max: $(q $h "SYSTEM FLUSH LOGS; SELECT round(quantile(0.5)(memory_usage)/1048576,1), round(quantile(0.99)(memory_usage)/1048576,1), round(max(memory_usage)/1048576,1) FROM system.query_log WHERE type='QueryFinish' AND query LIKE 'SELECT user_id, count()%'" | tr '\t' ' ')"; done >> "$R/final.txt"
touch "$R/.stop"; wait $SAMPLER 2>/dev/null
docker logs loadgen > "$R/loadgen.log" 2>&1
cp out/acked.txt out/writer.err out/reader.err "$R/" 2>/dev/null
ev "teardown"; ./scripts/lab.sh teardown > "$R/teardown.log" 2>&1
ev "left over: $(docker ps -a --format '{{.Names}}' | grep -cE '^(keeper-|ch-|haproxy|loadgen)') containers, $(docker volume ls -q | grep -c '^ch-ha') volumes"
ev "DONE"
