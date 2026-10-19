# Manual setup

Build the same topology as `scripts/deploy.sh`, from this directory, with every command written out. The two are the same procedure: `./scripts/lab.sh deploy` is the wrapper, and the blocks below are what it runs.

Run the `bash` blocks in order, in one shell, with the working directory set to `20261019-mysql-async-replication-ha`. A block defines `ROOT`, `COMPOSE`, and the helper functions used by the later blocks.

This was executed verbatim on a clean Docker state (project volumes removed) on 2026-10-19.

## What you need on the host

- Docker Engine and the `docker compose` plugin
- `curl` and `python3` (the Orchestrator discovery check parses JSON)
- `sudo` only if `iptables-legacy` exists and its FORWARD policy is DROP

The lab host used for the write-up had no systemd unit for Docker. Docker was installed from the distro packages (`docker.io` 29.1.3 and `docker-compose-v2`) and `dockerd` was started by hand. That is host bootstrap, not part of the topology:

```text
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo dockerd &
sudo chmod 666 /var/run/docker.sock
```

## Configuration files these commands mount

The commands do not generate the config files. They are in the repository and they are the configuration.

`docker/mysql/mysql-1.cnf` is the source. `server_id=1`, `report_host=mysql-1`, GTID and binary logging on, `log_replica_updates=ON`, `relay_log_recovery=ON`, `replica_net_timeout=6`, `mysql_native_password=ON`, `read_only=OFF`, `super_read_only=OFF`. `mysql-2.cnf` and `mysql-3.cnf` are the same with `server_id` 2 and 3, `report_host` `mysql-2` and `mysql-3`, and both `read_only=ON` and `super_read_only=ON`.

`super_read_only` is only in the replica files. The official image entrypoint refuses to initialise a datadir when `super_read_only=ON` is already set, and the replicas never run that initialisation: they receive a copy of the source datadir.

`docker/proxysql/proxysql.cnf` sets `admin_credentials="admin:admin"`, `stats_credentials="stats:stats"`, `web_enabled=true`, `web_port=6080`, monitor user `monitor` / `monitor`, `mysql-monitor_writer_is_also_reader=false`, `shun_on_failures=2`, `shun_recovery_time_sec=10`, ping interval 1000 ms, `server_version="8.4.11"`. The first start must pass `-c /etc/proxysql.cnf`. After `proxysql.db` exists, ProxySQL keeps the on-disk admin database.

`docker/orchestrator/orchestrator.conf.json` is the Orchestrator config mounted over the image default. The image default is a Percona-operator Raft / semi-sync layout and is not used. The container is built from `docker/orchestrator/Dockerfile` (`percona/percona-orchestrator:3.2.6-24` plus the MariaDB client and `proxysql-failover-hook.sh`) and runs as uid 0 because the sqlite volume and the hook log are root-owned. The upstream image user is 1001.

`docker/docker-compose.yml` names the project `mysql-async-ha` and the network `mysql-ha`. Volume names below (`mysql-async-ha_mysql1` and so on) come from that project name. There is no restart policy: `docker kill` stays down.

## 1. Firewall check, images, empty volumes

Docker 29 on a host without systemd can program nftables and leave `iptables-legacy` FORWARD policy DROP. Packets between containers on the `mysql-ha` bridge are then dropped, and a replica sits in `Connecting` with error 110. A host whose FORWARD policy is already ACCEPT is left alone.

```bash
set -euo pipefail
if [ ! -f docker/docker-compose.yml ]; then
    echo "cd into 20261019-mysql-async-replication-ha first" >&2
    exit 1
fi
ROOT="$(pwd)"
COMPOSE=(docker compose -f "$ROOT/docker/docker-compose.yml")

mysql_exec() {
    local container="$1"
    shift
    docker exec "$container" mysql --protocol=socket -uroot -pmysql --batch --skip-column-names "$@"
}

wait_mysql() {
    local container="$1"
    local i
    # mysqladmin ping succeeds against the entrypoint's temporary server
    # (socket only, port 0). That server is shut down before the real one
    # starts, and a query in that window fails with error 2002. A fresh
    # datadir logs "MySQL init process done. Ready for start up." once the
    # temporary server is gone. A cloned datadir skips that line.
    for i in $(seq 1 90); do
        local logs
        logs="$(docker logs "$container" 2>&1 || true)"
        if printf '%s\n' "$logs" | grep -q "MySQL init process done. Ready for start up."; then
            if docker exec "$container" mysql --protocol=socket -uroot -pmysql -e "SELECT 1" >/dev/null 2>&1; then
                echo "$container is accepting connections"
                return 0
            fi
        elif printf '%s\n' "$logs" | grep -q "ready for connections" \
            && ! printf '%s\n' "$logs" | grep -q "Initializing database files"; then
            if docker exec "$container" mysql --protocol=socket -uroot -pmysql -e "SELECT 1" >/dev/null 2>&1; then
                echo "$container is accepting connections"
                return 0
            fi
        fi
        sleep 2
    done
    echo "timed out waiting for $container" >&2
    docker logs --tail 80 "$container" >&2 || true
    exit 1
}

if command -v iptables-legacy >/dev/null 2>&1 && sudo -n iptables-legacy -S FORWARD 2>/dev/null | head -n 1 | grep -q -- '-P FORWARD DROP'; then
    echo "== iptables-legacy FORWARD policy is DROP; setting ACCEPT so containers can reach each other =="
    sudo iptables-legacy -P FORWARD ACCEPT
fi

echo "== pull images and build lab images =="
docker pull mysql:8.4.11
docker pull proxysql/proxysql:2.7.3
docker pull percona/percona-orchestrator:3.2.6-24
docker pull alpine:3.20
"${COMPOSE[@]}" build

echo "== remove any previous lab volumes =="
"${COMPOSE[@]}" down -v --remove-orphans
```

## 2. Initialise the source and create accounts

Start only `mysql-1`. The entrypoint creates the datadir and the root account (`MYSQL_ROOT_PASSWORD=mysql`, `MYSQL_ROOT_HOST=%`). It answers on a socket from a temporary server before that server is shut down, so the wait below looks for `MySQL init process done. Ready for start up.` and then a real `SELECT 1`, not `mysqladmin ping`.

MySQL 8.4 disables `mysql_native_password` unless the server was started with `mysql_native_password=ON`. ProxySQL 2.7.3 and this Orchestrator build authenticate with that plugin, so every lab account is created `IDENTIFIED WITH mysql_native_password`.

```bash
echo "== start the source and let the image initialise the datadir =="
"${COMPOSE[@]}" up -d mysql-1
wait_mysql mysql-1

echo "== create accounts on the source =="
docker exec -i mysql-1 mysql --protocol=socket -uroot -pmysql --batch --skip-column-names <<'SQL'
CREATE USER 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'repl';
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';

CREATE USER 'orchestrator'@'%' IDENTIFIED WITH mysql_native_password BY 'orchestrator';
GRANT SUPER, PROCESS, REPLICATION SLAVE, REPLICATION CLIENT, RELOAD,
      REPLICATION_SLAVE_ADMIN, SYSTEM_VARIABLES_ADMIN, CONNECTION_ADMIN,
      SERVICE_CONNECTION_ADMIN, BACKUP_ADMIN
  ON *.* TO 'orchestrator'@'%';
GRANT SELECT ON performance_schema.* TO 'orchestrator'@'%';
GRANT SELECT ON mysql.slave_master_info TO 'orchestrator'@'%';

CREATE USER 'monitor'@'%' IDENTIFIED WITH mysql_native_password BY 'monitor';
GRANT REPLICATION CLIENT ON *.* TO 'monitor'@'%';

CREATE DATABASE sbtest;
CREATE USER 'sbuser'@'%' IDENTIFIED WITH mysql_native_password BY 'sbpass';
GRANT ALL PRIVILEGES ON sbtest.* TO 'sbuser'@'%';
SQL
```

`repl` is the replication applier account. `orchestrator` is the topology user: it must be able to `CHANGE REPLICATION SOURCE`, set `read_only` / `super_read_only`, and read `performance_schema` plus `mysql.slave_master_info` (Orchestrator still queries that table by its historical name). `monitor` is the ProxySQL monitor and only needs `REPLICATION CLIENT`. `sbuser` is the application account, scoped to `sbtest`.

## 3. Clone the datadir onto the two replicas

Three independent `docker` entrypoints would each run their own bootstrap and each would execute a different GTID set. Orchestrator would then refuse to promote, because the replicas would not be subsets of the source.

`compose create` builds the replica containers so Compose owns the volumes. The source is stopped, and the datadir is copied. `auto.cnf` is removed on the replicas so the next start allocates a new `server_uuid` while `gtid_executed` stays the source's set.

```bash
echo "== create the replica volumes, then stop the source and clone its datadir =="
"${COMPOSE[@]}" create mysql-2 mysql-3
"${COMPOSE[@]}" stop mysql-1
docker run --rm \
    -v mysql-async-ha_mysql1:/from:ro \
    -v mysql-async-ha_mysql2:/to \
    alpine:3.20 \
    sh -c 'rm -rf /to/* /to/.[!.]* 2>/dev/null || true; cp -a /from/. /to/ && rm -f /to/auto.cnf'
docker run --rm \
    -v mysql-async-ha_mysql1:/from:ro \
    -v mysql-async-ha_mysql3:/to \
    alpine:3.20 \
    sh -c 'rm -rf /to/* /to/.[!.]* 2>/dev/null || true; cp -a /from/. /to/ && rm -f /to/auto.cnf'
```

## 4. Start all three servers and attach replication

MySQL 8.4 removed `CHANGE MASTER TO` and `SHOW SLAVE STATUS`. The statements are `CHANGE REPLICATION SOURCE TO` and `SHOW REPLICA STATUS`.

```bash
echo "== start source and both replicas =="
"${COMPOSE[@]}" up -d mysql-1 mysql-2 mysql-3
wait_mysql mysql-1
wait_mysql mysql-2
wait_mysql mysql-3

echo "== confirm the clone did not invent a GTID, then attach the replicas =="
mysql_exec mysql-1 -e "SELECT @@global.server_uuid AS uuid, @@global.gtid_executed AS gtid, @@global.report_host AS report_host, @@global.read_only AS read_only, @@global.super_read_only AS super_read_only"
mysql_exec mysql-2 -e "SELECT @@global.server_uuid AS uuid, @@global.gtid_executed AS gtid, @@global.report_host AS report_host, @@global.read_only AS read_only, @@global.super_read_only AS super_read_only"
mysql_exec mysql-3 -e "SELECT @@global.server_uuid AS uuid, @@global.gtid_executed AS gtid, @@global.report_host AS report_host, @@global.read_only AS read_only, @@global.super_read_only AS super_read_only"

for replica in mysql-2 mysql-3; do
    docker exec -i "$replica" mysql --protocol=socket -uroot -pmysql --batch --skip-column-names <<'SQL'
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='mysql-1',
    SOURCE_PORT=3306,
    SOURCE_USER='repl',
    SOURCE_PASSWORD='repl',
    SOURCE_AUTO_POSITION=1,
    SOURCE_CONNECT_RETRY=1,
    SOURCE_RETRY_COUNT=86400;
START REPLICA;
SQL
done

echo "== wait until both replicas are applying =="
for replica in mysql-2 mysql-3; do
    ok=0
    for _ in $(seq 1 30); do
        state="$(mysql_exec "$replica" -e "
            SELECT SERVICE_STATE FROM performance_schema.replication_connection_status WHERE CHANNEL_NAME='';
            SELECT IFNULL(
                (SELECT SERVICE_STATE FROM performance_schema.replication_applier_status_by_coordinator WHERE CHANNEL_NAME='' LIMIT 1),
                (SELECT SERVICE_STATE FROM performance_schema.replication_applier_status WHERE CHANNEL_NAME='' LIMIT 1)
            );
        ")"
        io_state="$(printf '%s\n' "$state" | sed -n '1p')"
        sql_state="$(printf '%s\n' "$state" | sed -n '2p')"
        echo "$replica receiver=$io_state applier=$sql_state"
        if [ "$io_state" = "ON" ] && [ "$sql_state" = "ON" ]; then
            ok=1
            break
        fi
        sleep 2
    done
    if [ "$ok" -ne 1 ]; then
        echo "$replica did not start replication" >&2
        docker exec "$replica" mysql --protocol=socket -uroot -pmysql -e "SHOW REPLICA STATUS\G" >&2 || true
        exit 1
    fi
done
```

The three `gtid_executed` values printed above are the same UUID and the same range. The three `server_uuid` values differ. Both replicas report `read_only=1` and `super_read_only=1`.

## 5. ProxySQL

All three servers are inserted into writer hostgroup 10. The replication-hostgroup row tells the monitor to check `read_only` and move a `read_only=1` server to reader hostgroup 20. `mysql-monitor_writer_is_also_reader` is set false again at runtime so a restarted ProxySQL that ignored the cnf still matches this lab.

`sbuser` defaults to hostgroup 10 with `transaction_persistent=1`. A transaction that starts on the writer stays on the writer. That is what you want for `oltp_read_write`. It is also why a `^SELECT` query rule does not split reads that run inside `BEGIN` (see the experiments).

```bash
echo "== start ProxySQL and register the three servers =="
"${COMPOSE[@]}" up -d proxysql
for _ in $(seq 1 30); do
    if docker exec proxysql mysql --protocol=tcp --silent -h127.0.0.1 -P6032 -uadmin -padmin -e "SELECT 1" >/dev/null 2>&1; then
        echo "proxysql admin is up"
        break
    fi
    sleep 1
done

docker exec -i proxysql mysql --protocol=tcp -h127.0.0.1 -P6032 -uadmin -padmin <<'SQL'
DELETE FROM mysql_servers;
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections) VALUES
    (10, 'mysql-1', 3306, 200),
    (10, 'mysql-2', 3306, 200),
    (10, 'mysql-3', 3306, 200);
DELETE FROM mysql_replication_hostgroups;
INSERT INTO mysql_replication_hostgroups (writer_hostgroup, reader_hostgroup, check_type, comment)
VALUES (10, 20, 'read_only', 'async GTID: writer 10, reader 20');
DELETE FROM mysql_users;
INSERT INTO mysql_users (username, password, default_hostgroup, transaction_persistent, active)
VALUES ('sbuser', 'sbpass', 10, 1, 1);
UPDATE global_variables SET variable_value='false' WHERE variable_name='mysql-monitor_writer_is_also_reader';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
SQL

echo "== wait until read_only placement has split writer and readers =="
placed=0
for _ in $(seq 1 20); do
    docker exec proxysql mysql --protocol=tcp -h127.0.0.1 -P6032 -uadmin -padmin -e \
        "SELECT hostgroup_id, hostname, status FROM runtime_mysql_servers ORDER BY hostgroup_id, hostname"
    writer="$(docker exec proxysql mysql --protocol=tcp -N -h127.0.0.1 -P6032 -uadmin -padmin -e \
        "SELECT hostname FROM runtime_mysql_servers WHERE hostgroup_id=10 AND status='ONLINE'")"
    readers="$(docker exec proxysql mysql --protocol=tcp -N -h127.0.0.1 -P6032 -uadmin -padmin -e \
        "SELECT hostname FROM runtime_mysql_servers WHERE hostgroup_id=20 AND status='ONLINE' ORDER BY hostname")"
    if [ "$writer" = "mysql-1" ] && [ "$readers" = $'mysql-2\nmysql-3' ]; then
        placed=1
        break
    fi
    sleep 1
done
if [ "$placed" -ne 1 ]; then
    echo "ProxySQL did not place mysql-1 in HG 10 and the replicas in HG 20" >&2
    exit 1
fi
```

ProxySQL 2.7.3's `mysql_replication_hostgroups` has `writer_hostgroup`, `reader_hostgroup`, `check_type`, and `comment`. There is no `writer_is_also_reader` column on that table. The column exists on `mysql_group_replication_hostgroups` and `mysql_galera_hostgroups`. The global `mysql-monitor_writer_is_also_reader` is what async replication consults, and only on a `read_only` transition. See experiment C.

Hostgroup 30 is not created here. The failover hook inserts the failed source into hostgroup 30 as `OFFLINE_HARD`. What runtime actually keeps is described with the failover measurement.

## 6. Orchestrator

Upstream Orchestrator 3.2.6 from openark does not speak MySQL 8.4 (`CHANGE REPLICATION SOURCE`, `performance_schema` replication tables). `percona/percona-orchestrator:3.2.6-24` does. `ReplicationCredentialsQuery` on this build must return five columns: user, password, and three TLS paths. Two columns fail discovery.

`DetectPromotionRuleQuery` makes the successor deterministic: `mysql-2` is `prefer`, `mysql-3` is `neutral`, anything else (including the old source) is `must_not`. `RecoverMasterClusterFilters` is `[".*"]`, which turns automatic master recovery on. `ApplyMySQLPromotionAfterMasterFailover` clears `read_only` / `super_read_only` (because `UseSuperReadOnly` is true) and repoints the surviving replica. `PostMasterFailoverProcesses` runs the hook.

There is no ProxySQL hostgroup driver in Orchestrator 3.2.6. The hook is the supported extension point.

```bash
echo "== start Orchestrator and discover mysql-1 =="
"${COMPOSE[@]}" up -d orchestrator
for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:13000/api/status" >/dev/null; then
        echo "orchestrator http is up"
        break
    fi
    sleep 1
done
curl -sf "http://127.0.0.1:13000/api/discover/mysql-1/3306" || true

discovered=0
for _ in $(seq 1 30); do
    count="$(curl -sf "http://127.0.0.1:13000/api/clusters-info" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["CountInstances"] if d else 0)' 2>/dev/null || echo 0)"
    echo "orchestrator instances=$count"
    if [ "$count" = "3" ]; then
        discovered=1
        break
    fi
    sleep 2
done
if [ "$discovered" -ne 1 ]; then
    echo "Orchestrator did not discover 3 instances" >&2
    docker logs --tail 80 orchestrator >&2 || true
    exit 1
fi
```

`/api/instances` returns 404 on this build. `/api/clusters-info` returns `CountInstances`. The topology UI is `/web/cluster/alias/mysql-1` while `mysql-1` is the primary (`DetectClusterAliasQuery` is `SELECT @@report_host`). After failover the alias follows the new primary.

Poll interval is 2 seconds and the MySQL connect timeout is 1 second. Those are lab values so a crash shows up in one poll. Production defaults are slower; the failover time in the write-up is this configuration, not a generic Orchestrator number.

## 7. sysbench

`oltp_read_write` prepare (4 tables, 10 000 rows) goes through ProxySQL as `sbuser`, so it lands on the writer. The long-running container uses `--report-interval=1`, `--mysql-ignore-errors=all`, `--db-ps-mode=disable`, and a timestamp prefix on each line.

`--db-ps-mode=disable` matters once query rules exist. A prepared statement pins its backend at `COM_STMT_PREPARE`, and ProxySQL does not re-evaluate `match_digest` for later executes. The text protocol lets a `^SELECT` rule see the statement.

`--mysql-ignore-errors=all` keeps sysbench alive across failover and counts the failures in `err/s`. Without it, the first server error ends the run and there is no recovery line to read.

```bash
echo "== sysbench prepare, then a continuous oltp_read_write through ProxySQL =="
"${COMPOSE[@]}" run --rm --no-deps --entrypoint sysbench sysbench \
    /usr/share/sysbench/oltp_read_write.lua \
    --db-driver=mysql \
    --mysql-host=proxysql \
    --mysql-port=6033 \
    --mysql-user=sbuser \
    --mysql-password=sbpass \
    --mysql-db=sbtest \
    --tables=4 \
    --table-size=10000 \
    --threads=4 \
    --db-ps-mode=disable \
    prepare
"${COMPOSE[@]}" up -d sysbench

echo "== lab is up =="
echo "ProxySQL MySQL   127.0.0.1:16033   sbuser / sbpass"
echo "ProxySQL admin   127.0.0.1:16032   admin / admin"
echo "ProxySQL web     https://127.0.0.1:16080/   stats / stats (digest)"
echo "Orchestrator     http://127.0.0.1:13000/"
echo "MySQL source     127.0.0.1:13316   root / mysql"
echo "MySQL replicas   127.0.0.1:13317 and 127.0.0.1:13318"
```

## Check the steady state

```bash
./scripts/lab.sh verify
```

`verify` checks that `mysql-1` answers, both replicas are `super_read_only=1` with receiver and applier `ON`, ProxySQL's only ONLINE writer-hostgroup server is `mysql-1`, Orchestrator reports 3 instances, and the sysbench container is running. It describes the initial topology. After a failover it fails on purpose, because the writer is no longer `mysql-1`.

## Tear it down

```bash
./scripts/lab.sh teardown
```

That is `docker compose -f docker/docker-compose.yml down -v --remove-orphans`.
