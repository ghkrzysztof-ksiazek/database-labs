# Manual setup

Every command `scripts/deploy.sh` runs, typed out, with the output from the run on 29 October 2026 on a Debian 13 host (Madeira time, WET). Run everything from one shell, in the order given. The experiments are in the [README](../README.md).

The only differences from `deploy.sh`: `deploy.sh` pulls the images first, removes any earlier lab, and waits in loops where this page uses a fixed `sleep`.

## 1. Check Docker

```bash
docker version --format '{{.Server.Version}}'
docker compose version --short
# Linux only (skip on macOS / Docker Desktop): containers on one bridge must reach each other.
# If the first line is "-P FORWARD DROP", open it for the lab:
sudo iptables-legacy -S FORWARD | head -1
sudo iptables-legacy -P FORWARD ACCEPT
```

**What you should see.** Docker answers with a server version. On Linux, the first `iptables-legacy` line should be `-P FORWARD ACCEPT` after the second command. On macOS skip both `iptables` lines.

**How to check.** `docker version` prints a version, not an error.

## 2. Directory layout

```bash
mkdir -p clickhouse-ha/docker/{keeper,clickhouse/config.d,clickhouse/users.d,clickhouse/macros,haproxy} \
         clickhouse-ha/scripts clickhouse-ha/out
cd clickhouse-ha
```

**What you should see.** An empty `clickhouse-ha` tree, with your shell inside it.

**How to check.** `ls docker` lists `clickhouse haproxy keeper`.

## 3. Three Keeper configs

```bash
for i in 1 2 3; do cat > docker/keeper/keeper-$i.xml <<EOF
<clickhouse>
    <logger>
        <level>information</level>
        <console>true</console>
    </logger>
    <listen_host>0.0.0.0</listen_host>
    <keeper_server>
        <tcp_port>9181</tcp_port>
        <server_id>$i</server_id>
        <log_storage_path>/var/lib/clickhouse-keeper/coordination/log</log_storage_path>
        <snapshot_storage_path>/var/lib/clickhouse-keeper/coordination/snapshots</snapshot_storage_path>
        <coordination_settings>
            <operation_timeout_ms>10000</operation_timeout_ms>
            <session_timeout_ms>30000</session_timeout_ms>
            <raft_logs_level>warning</raft_logs_level>
        </coordination_settings>
        <four_letter_word_white_list>ruok,mntr,stat,srvr,conf,isro</four_letter_word_white_list>
        <raft_configuration>
            <server><id>1</id><hostname>keeper-1</hostname><port>9234</port></server>
            <server><id>2</id><hostname>keeper-2</hostname><port>9234</port></server>
            <server><id>3</id><hostname>keeper-3</hostname><port>9234</port></server>
        </raft_configuration>
    </keeper_server>
</clickhouse>
EOF
done
```

**What you should see.** Three files, identical except for `server_id`.

**How to check.** `grep server_id docker/keeper/*.xml`

## 4a. ClickHouse server config

```bash
cat > docker/clickhouse/config.d/cluster.xml <<'EOF'
<clickhouse>
    <logger>
        <level>information</level>
        <console>true</console>
    </logger>
    <listen_host>0.0.0.0</listen_host>

    <!-- Lab-sized memory. "On macOS" in the post explains both settings. -->
    <merge_tree>
        <!-- drop merged-away parts after 10 s instead of 480 s -->
        <old_parts_lifetime>10</old_parts_lifetime>
        <cleanup_delay_period>1</cleanup_delay_period>
        <max_cleanup_delay_period>2</max_cleanup_delay_period>
    </merge_tree>
    <max_server_memory_usage>4000000000</max_server_memory_usage>
    <mark_cache_size>268435456</mark_cache_size>

    <!-- the Keeper ensemble every replica talks to -->
    <zookeeper>
        <node><host>keeper-1</host><port>9181</port></node>
        <node><host>keeper-2</host><port>9181</port></node>
        <node><host>keeper-3</host><port>9181</port></node>
        <session_timeout_ms>30000</session_timeout_ms>
        <operation_timeout_ms>10000</operation_timeout_ms>
    </zookeeper>

    <!-- one shard, two replicas -->
    <remote_servers replace="true">
        <lab>
            <shard>
                <internal_replication>true</internal_replication>
                <replica><host>ch-1</host><port>9000</port><user>default</user><password>chpass</password></replica>
                <replica><host>ch-2</host><port>9000</port><user>default</user><password>chpass</password></replica>
            </shard>
        </lab>
    </remote_servers>

    <distributed_ddl>
        <path>/clickhouse/task_queue/ddl</path>
    </distributed_ddl>
</clickhouse>
EOF
```

**What you should see.** One shared file for both servers.

**How to check.** `cat docker/clickhouse/config.d/cluster.xml`

## 4b. Macros

```bash
for i in 1 2; do cat > docker/clickhouse/macros/ch-$i.xml <<EOF
<clickhouse>
    <macros>
        <cluster>lab</cluster>
        <shard>01</shard>
        <replica>ch-$i</replica>
    </macros>
    <interserver_http_host>ch-$i</interserver_http_host>
</clickhouse>
EOF
done
```

**What you should see.** Two files, `ch-1.xml` and `ch-2.xml`.

**How to check.** `grep replica docker/clickhouse/macros/*.xml`

## 4c. Application user

```bash
cat > docker/clickhouse/users.d/app.xml <<'EOF'
<clickhouse>
    <users>
        <app>
            <password>app</password>
            <networks><ip>::/0</ip></networks>
            <profile>default</profile>
            <quota>default</quota>
            <grants>
                <query>GRANT SELECT, INSERT ON lab.*</query>
            </grants>
        </app>
    </users>
</clickhouse>
EOF
```

**What you should see.** One file defining `app` / `app`.

**How to check.** `cat docker/clickhouse/users.d/app.xml`

## 5. HAProxy

```bash
cat > docker/haproxy/haproxy.cfg <<'EOF'
global
    log stdout format raw local0 info

defaults
    log     global
    timeout connect 1s
    timeout client  60s
    timeout server  60s

# the HAProxy stats page
listen stats
    bind *:8404
    mode http
    stats enable
    stats uri /
    stats refresh 2s

# ClickHouse native protocol (clickhouse-client, most drivers)
frontend ch_native
    bind *:9000
    mode tcp
    option tcplog
    default_backend ch_native

backend ch_native
    mode tcp
    balance roundrobin
    option httpchk GET /replicas_status
    default-server check port 8123 inter 1s fall 2 rise 2 on-marked-down shutdown-sessions
    server ch-1 ch-1:9000
    server ch-2 ch-2:9000

# ClickHouse HTTP interface
frontend ch_http
    bind *:8123
    mode http
    option httplog
    default_backend ch_http

backend ch_http
    mode http
    balance roundrobin
    option httpchk GET /replicas_status
    default-server check inter 1s fall 2 rise 2 on-marked-down shutdown-sessions
    server ch-1 ch-1:8123
    server ch-2 ch-2:8123
EOF
```

**What you should see.** One config with a native and an HTTP frontend.

**How to check.** `grep server docker/haproxy/haproxy.cfg`

## 6. Compose file

```bash
cat > docker/docker-compose.yml <<'EOF'
name: ch-ha

x-keeper: &keeper
  image: clickhouse/clickhouse-keeper:25.8
  networks: [ch-ha]

x-clickhouse: &clickhouse
  image: clickhouse/clickhouse-server:25.8
  networks: [ch-ha]
  environment:
    CLICKHOUSE_PASSWORD: chpass
    CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: "1"
  ulimits:
    nofile: { soft: 262144, hard: 262144 }
  depends_on: [keeper-1, keeper-2, keeper-3]

services:
  keeper-1:
    <<: *keeper
    container_name: keeper-1
    hostname: keeper-1
    volumes:
      - ./keeper/keeper-1.xml:/etc/clickhouse-keeper/keeper_config.d/keeper.xml:ro
      - keeper-1:/var/lib/clickhouse-keeper
    ports: ["127.0.0.1:19181:9181"]
  keeper-2:
    <<: *keeper
    container_name: keeper-2
    hostname: keeper-2
    volumes:
      - ./keeper/keeper-2.xml:/etc/clickhouse-keeper/keeper_config.d/keeper.xml:ro
      - keeper-2:/var/lib/clickhouse-keeper
    ports: ["127.0.0.1:19182:9181"]
  keeper-3:
    <<: *keeper
    container_name: keeper-3
    hostname: keeper-3
    volumes:
      - ./keeper/keeper-3.xml:/etc/clickhouse-keeper/keeper_config.d/keeper.xml:ro
      - keeper-3:/var/lib/clickhouse-keeper
    ports: ["127.0.0.1:19183:9181"]

  ch-1:
    <<: *clickhouse
    container_name: ch-1
    hostname: ch-1
    volumes:
      - ./clickhouse/config.d/cluster.xml:/etc/clickhouse-server/config.d/cluster.xml:ro
      - ./clickhouse/macros/ch-1.xml:/etc/clickhouse-server/config.d/macros.xml:ro
      - ./clickhouse/users.d/app.xml:/etc/clickhouse-server/users.d/app.xml:ro
      - ch-1:/var/lib/clickhouse
    ports: ["127.0.0.1:18124:8123", "127.0.0.1:19001:9000"]
  ch-2:
    <<: *clickhouse
    container_name: ch-2
    hostname: ch-2
    volumes:
      - ./clickhouse/config.d/cluster.xml:/etc/clickhouse-server/config.d/cluster.xml:ro
      - ./clickhouse/macros/ch-2.xml:/etc/clickhouse-server/config.d/macros.xml:ro
      - ./clickhouse/users.d/app.xml:/etc/clickhouse-server/users.d/app.xml:ro
      - ch-2:/var/lib/clickhouse
    ports: ["127.0.0.1:18125:8123", "127.0.0.1:19002:9000"]

  haproxy:
    image: haproxy:3.2
    container_name: haproxy
    hostname: haproxy
    networks: [ch-ha]
    volumes:
      - ./haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    ports:
      - "127.0.0.1:18123:8123"
      - "127.0.0.1:19000:9000"
      - "127.0.0.1:18404:8404"
    depends_on: [ch-1, ch-2]

networks:
  ch-ha:
    name: ch-ha

volumes:
  keeper-1:
  keeper-2:
  keeper-3:
  ch-1:
  ch-2:
EOF
```

**What you should see.** Six services, five volumes, one network.

**How to check.** `docker compose -f docker/docker-compose.yml config --services`

## 7. Start and wait

```bash
docker compose -f docker/docker-compose.yml up -d

# wait until both servers answer a query
until docker exec ch-1 clickhouse-client --password chpass -q "SELECT 1" >/dev/null 2>&1 \
   && docker exec ch-2 clickhouse-client --password chpass -q "SELECT 1" >/dev/null 2>&1; do
  sleep 1
done; echo ready
```

**What you should see.** `ready` after a few seconds once the images are pulled.

**How to check.** `docker ps` lists keeper-1..3, ch-1, ch-2, haproxy.

## 8a. Keeper roles

```bash
# Keeper roles: one leader, two followers
mntr() {
  for k in keeper-1 keeper-2 keeper-3; do
    s=$(docker exec $k bash -c 'exec 3<>/dev/tcp/127.0.0.1/9181; echo mntr >&3; cat <&3' 2>/dev/null \
        | awk '$1=="zk_server_state"{print $2}')
    echo -n "$k=${s:-down} "
  done; echo
}
mntr
```

Output from the run:

```text
keeper-1=leader keeper-2=follower keeper-3=follower
```

**What you should see.** One leader and two followers. Which node leads can differ.

**How to check.** Run `mntr` again; the same three roles.

## 8b. Cluster, Keeper connection, health check, HAProxy

```bash
docker exec ch-1 clickhouse-client --password chpass -q "SELECT version()"

docker exec ch-1 clickhouse-client --password chpass -q "
  SELECT cluster, shard_num, replica_num, host_name, port
  FROM system.clusters WHERE cluster = 'lab'
  FORMAT PrettyCompactMonoBlock"

docker exec ch-1 clickhouse-client --password chpass -q "
  SELECT host, port, is_expired FROM system.zookeeper_connection"

curl -s http://127.0.0.1:18124/replicas_status

sleep 3   # HAProxy needs two good checks (rise 2) before it shows UP
curl -s "http://127.0.0.1:18404/;csv" | awk -F, '$1=="ch_native" {print $2"="$18}'
```

Output from the run:

```text
25.8.33.6
   ┌─cluster─┬─shard_num─┬─replica_num─┬─host_name─┬─port─┐
1. │ lab     │         1 │           1 │ ch-1      │ 9000 │
2. │ lab     │         1 │           2 │ ch-2      │ 9000 │
   └─────────┴───────────┴─────────────┴───────────┴──────┘
keeper-3	9181	0
Ok.
FRONTEND=OPEN
ch-1=UP
ch-2=UP
BACKEND=UP
```

**What you should see.** Two cluster rows, `is_expired` 0, `Ok.`, both servers UP.

**How to check.** If HAProxy shows DOWN, wait a few seconds and run the last line again.

## 9. Database and replicated table

```bash
cat > docker/clickhouse/schema.sql <<'EOF'
CREATE DATABASE IF NOT EXISTS lab ON CLUSTER lab;

CREATE TABLE IF NOT EXISTS lab.events ON CLUSTER lab
(
    ts      DateTime64(3),
    batch   UInt32,
    id      UInt64,
    user_id UInt32,
    value   Float64
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/lab/events', '{replica}')
PARTITION BY toYYYYMMDD(ts)
ORDER BY (user_id, ts);
EOF

docker exec -i ch-1 clickhouse-client --password chpass --multiquery < docker/clickhouse/schema.sql
```

Output from the run:

```text
ch-1	9000	0		1	0
ch-2	9000	0		0	0
ch-1	9000	0		1	0
ch-2	9000	0		0	0
```

**What you should see.** Status 0 from both servers, for both statements.

**How to check.** `docker exec ch-2 clickhouse-client --password chpass -q "SHOW TABLES FROM lab"` prints `events`.

## 10a. A million rows

```bash
docker exec ch-1 clickhouse-client --password chpass -q "
  INSERT INTO lab.events
  SELECT now64(3) - toIntervalSecond(number % 86400), 0, number,
         number % 10000, (number % 1000) / 10
  FROM numbers(1000000)"

for h in ch-1 ch-2; do
  echo -n "$h: "
  docker exec $h clickhouse-client --password chpass -q "
    SELECT count(), uniqExact(user_id), round(sum(value)) FROM lab.events"
done

docker exec ch-2 clickhouse-client --password chpass -q "
  SELECT replica_name, is_leader, is_readonly, absolute_delay,
         queue_size, active_replicas, total_replicas
  FROM system.replicas FORMAT Vertical"
```

Output from the run:

```text
ch-1: 1000000	10000	49950000
ch-2: 1000000	10000	49950000
Row 1:
──────
replica_name:    ch-2
is_leader:       1
is_readonly:     0
absolute_delay:  0
queue_size:      0
active_replicas: 2
total_replicas:  2
```

**What you should see.** The same three numbers on both servers, and `queue_size` 0.

**How to check.** Run the count loop again if ch-2 is still fetching.

## 10b. Round robin through HAProxy

```bash
curl -s -u app:app http://127.0.0.1:18123/ --data-binary "SELECT hostName(), count() FROM lab.events"
curl -s -u app:app http://127.0.0.1:18123/ --data-binary "SELECT hostName(), count() FROM lab.events"
```

Output from the run:

```text
ch-1	1000000
ch-2	1000000
```

**What you should see.** One answer from each server.

**How to check.** Run it a few more times; the host alternates.

## 11. The load generator

```bash
cat > scripts/load.sh <<'EOF'
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
EOF
chmod +x scripts/load.sh

docker run -d --name loadgen --network ch-ha \
  -v "$PWD/scripts/load.sh:/load.sh:ro" -v "$PWD/out:/out" \
  --entrypoint bash clickhouse/clickhouse-server:25.8 /load.sh

docker logs -f loadgen    # Ctrl-C stops watching; loadgen keeps running
```

Output from the run:

```text
21:01:08 [ 8s ] inserts/s: 26 ins_err/s: 0 selects/s: 27 sel_err/s: 0
21:01:09 [ 9s ] inserts/s: 28 ins_err/s: 0 selects/s: 28 sel_err/s: 0
21:01:10 [ 10s ] inserts/s: 23 ins_err/s: 0 selects/s: 24 sel_err/s: 0
```

**What you should see.** One line per second, about 25 inserts and 25 selects, no errors.

**How to check.** `docker logs --tail 5 loadgen`

## 12. The healthy-state check

```bash
cat > scripts/verify.sh <<'EOF'
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
EOF
chmod +x scripts/verify.sh
./scripts/verify.sh
```

Output from the run:

```text
verify: steady state ok (keeper 1 leader + 2 followers, 2 writable replicas, 1000000 seed rows each, haproxy 2/2 UP)
```

**What you should see.** `verify: steady state ok`.

**How to check.** `./scripts/verify.sh` again at any time before the experiments.

## Clean up

```bash
docker rm -f loadgen
docker compose -f docker/docker-compose.yml down -v --remove-orphans
rm -rf out
```

**What you should see.** No lab containers, volumes or network left.

**How to check.** `docker ps -a --format '{{.Names}}' | grep -E '^(keeper-|ch-|haproxy|loadgen)'` prints nothing.
