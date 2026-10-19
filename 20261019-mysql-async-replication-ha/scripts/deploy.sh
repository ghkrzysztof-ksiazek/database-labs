#!/usr/bin/env bash
# Build the lab from an empty Docker state. Every step is also written out in
# docs/manual-setup.md; keep the two in lockstep.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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

# Docker 29 on a host without systemd can program nftables while leaving
# iptables-legacy FORWARD policy DROP. Packets between containers on a custom
# bridge are then dropped, and replicas sit in "Connecting" with error 110.
# A normal engine (FORWARD policy ACCEPT, or a single iptables backend) is
# not modified.
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
    writer="$(docker exec proxysql mysql --protocol=tcp -N -h127.0.0.1 -P6032 -uadmin -padmin -e \
        "SELECT hostname FROM runtime_mysql_servers WHERE hostgroup_id=10 AND status='ONLINE'")"
    readers="$(docker exec proxysql mysql --protocol=tcp -N -h127.0.0.1 -P6032 -uadmin -padmin -e \
        "SELECT hostname FROM runtime_mysql_servers WHERE hostgroup_id=20 AND status='ONLINE' ORDER BY hostname")"
    # Print the table after the check, so the lines you read are the lines that were judged.
    docker exec proxysql mysql --protocol=tcp -h127.0.0.1 -P6032 -uadmin -padmin -e \
        "SELECT hostgroup_id, hostname, status FROM runtime_mysql_servers ORDER BY hostgroup_id, hostname"
    if [ "$writer" = "mysql-1" ] && [ "$readers" = $'mysql-2\nmysql-3' ]; then
        echo "ProxySQL placement ok"
        placed=1
        break
    fi
    sleep 1
done
if [ "$placed" -ne 1 ]; then
    echo "ProxySQL did not place mysql-1 in HG 10 and the replicas in HG 20" >&2
    exit 1
fi

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
echo "ProxySQL admin   127.0.0.1:16032   radmin / radmin"
echo "ProxySQL web     https://127.0.0.1:16080/   stats / stats (digest)"
echo "Orchestrator     http://127.0.0.1:13000/"
echo "MySQL source     127.0.0.1:13316   root / mysql"
echo "MySQL replicas   127.0.0.1:13317 and 127.0.0.1:13318"
