#!/usr/bin/env bash
# Pretend to be the application: one writer and one reader, both through HAProxy.
# Prints one line per second: inserts ok/err, selects ok/err.
# Every statement opens a new connection, so a dead backend shows up as an error.
set -u
HOST=${HOST:-haproxy}
OUT=${OUT:-/out}
mkdir -p "$OUT"
: > "$OUT/acked.txt"
CH="clickhouse-client --host $HOST --port 9000 --user app --password app --connect_timeout 1 --receive_timeout 10 --send_timeout 10"

writer() {
  local batch=0
  while true; do
    batch=$((batch + 1))
    if $CH -q "INSERT INTO lab.events SELECT now64(3), $batch, number, rand() % 10000, rand() / 1e6 FROM numbers(1000)" 2>>"$OUT/writer.err"; then
      echo "$batch" >> "$OUT/acked.txt"; echo "$(date +%s) ok"  >> /tmp/w.log
    else
      echo "$(date +%s) err" >> /tmp/w.log; sleep 0.2
    fi
  done
}

reader() {
  while true; do
    if $CH -q "SELECT user_id, count(), avg(value) FROM lab.events GROUP BY user_id ORDER BY count() DESC LIMIT 10 FORMAT Null" 2>>"$OUT/reader.err"; then
      echo "$(date +%s) ok" >> /tmp/r.log
    else
      echo "$(date +%s) err" >> /tmp/r.log; sleep 0.2
    fi
  done
}

: > /tmp/w.log; : > /tmp/r.log
writer & reader &
start=$(date +%s)
while true; do
  sleep 1
  prev=$(( $(date +%s) - 1 ))
  wo=$(grep -c "^$prev ok"  /tmp/w.log); we=$(grep -c "^$prev err" /tmp/w.log)
  ro=$(grep -c "^$prev ok"  /tmp/r.log); re=$(grep -c "^$prev err" /tmp/r.log)
  printf '%s [ %ss ] inserts/s: %s ins_err/s: %s selects/s: %s sel_err/s: %s\n' \
    "$(date -d @$prev +%H:%M:%S)" "$((prev - start))" "$wo" "$we" "$ro" "$re"
done
