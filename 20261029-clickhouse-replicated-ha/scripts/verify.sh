#!/usr/bin/env bash
# Healthy starting state: Keeper has a leader and two followers, both replicas are
# writable and see each other, both have the seed rows, HAProxy has both backends UP.
# Safe to run while loadgen is writing: it checks the seed (batch 0), which does not
# change, and allows a short replication queue instead of demanding an empty one.
set -euo pipefail
fail() { echo "verify: FAILED - $*"; exit 1; }
q() { docker exec "$1" clickhouse-client --password chpass -q "$2"; }

leaders=0; followers=0
for k in keeper-1 keeper-2 keeper-3; do
  state=$(docker exec "$k" bash -c 'exec 3<>/dev/tcp/127.0.0.1/9181; echo mntr >&3; cat <&3' \
          | awk '$1=="zk_server_state"{print $2}')
  [ "$state" = leader ] && leaders=$((leaders+1))
  [ "$state" = follower ] && followers=$((followers+1))
done
[ "$leaders" -eq 1 ] && [ "$followers" -eq 2 ] || fail "keeper: $leaders leader(s), $followers follower(s)"

for h in ch-1 ch-2; do
  row=$(q "$h" "SELECT is_readonly, active_replicas, absolute_delay < 10 FROM system.replicas WHERE database='lab' AND table='events'")
  [ "$row" = "$(printf '0\t2\t1')" ] || fail "$h replica state: $row (want is_readonly 0, active_replicas 2, delay under 10 s = 1)"
done

c1=$(q ch-1 "SELECT count() FROM lab.events WHERE batch = 0"); c2=$(q ch-2 "SELECT count() FROM lab.events WHERE batch = 0")
[ "$c1" = 1000000 ] && [ "$c2" = 1000000 ] || fail "seed rows: ch-1=$c1 ch-2=$c2 (want 1000000 each)"

up=$(curl -s "http://127.0.0.1:18404/;csv" | awk -F, '$1=="ch_native" && $2 ~ /^ch-/ && $18=="UP"' | wc -l)
[ "$up" -eq 2 ] || fail "haproxy: $up of 2 native backends UP"

echo "verify: steady state ok (keeper 1 leader + 2 followers, 2 writable replicas, $c1 seed rows each, haproxy 2/2 UP)"
