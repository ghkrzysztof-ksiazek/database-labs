# Build the lab by hand

This page is the same procedure as `./scripts/lab.sh deploy`, written out so you can see what each step does. Run it if you want to learn the pieces. Run `deploy` if you only want the cluster, then come back to the [experiments](../README.md#experiment-a-the-source-dies).

Read [Ideas you need first](../README.md#ideas-you-need-first) before you start. The words source, replica, GTID, hostgroup, and hook are explained there in a few paragraphs each.

Run the `bash` blocks in order, in **one shell**, from the directory `20261019-mysql-async-replication-ha`. The first block defines helpers (`wait_mysql`, `mysql_exec`) that the later blocks use. A later block pasted into a new shell will fail with `COMPOSE: command not found`.

The expected output below is from a clean run on 2026-10-19 (empty volumes). Server UUIDs are random. Yours will differ. The shape of each result is what you are checking.

If a step does not match, jump to [When something goes wrong](../README.md#when-something-goes-wrong) before you continue. Later steps assume this one worked.

## What you need

| | |
| --- | --- |
| Docker | Engine plus the `docker compose` plugin. The host that produced this page had Engine 29.1.3 and Compose 2.40.3, on Ubuntu 24.04. |
| Memory | About 4 GB free. |
| Also | `curl`, `python3`. `sudo` only for the firewall check. |
| Ports | 13316–13318, 16032, 16033, 16080, 13000. Free these if something else is bound to them. |

The config files are already in `docker/`. You mount them; you do not retype them.

- `docker/mysql/mysql-1.cnf` is the source: GTID on, binary log on, `read_only` off. `mysql-2.cnf` and `mysql-3.cnf` match it, with their own `server_id` and `report_host`, and with `read_only` and `super_read_only` on. Replicas must reject writes, including from `root`.
- `docker/proxysql/proxysql.cnf` turns the web page on (HTTPS, port 6080, user `stats` / `stats`), sets the monitor account, and pings every second.
- `docker/orchestrator/orchestrator.conf.json` is the failover config. The image ships with a config for the Percona Kubernetes operator (a Raft group, semi-sync replication). This file replaces that config. This lab is one Orchestrator process and asynchronous replication.
- `docker/docker-compose.yml` names the project `mysql-async-ha` and the network `mysql-ha`. There is no restart policy, so `docker kill` stays down.

`super_read_only=ON` is only in the replica files. The official MySQL image will not initialise a brand-new data directory if that setting is already on. The replicas never initialise: they receive a copy of the source's files.

## 1. Make sure containers can talk, then pull the images

**What this does.** Pulls MySQL 8.4.11, ProxySQL 2.7.3, Percona Orchestrator 3.2.6, and a small Alpine image used as a copy tool. Builds the Orchestrator image (it adds a MySQL client for the hook) and the sysbench image. Deletes any previous lab volumes so you start from empty disks.

**Why.** A half-initialised data directory from a previous attempt is a confusing GTID history. Empty volumes keep this page repeatable.

On some Linux hosts Docker 29 programs one firewall backend and leaves the older one dropping forwarded packets. Replicas then sit in `Connecting` with error 110, which looks like a replication bug. The script checks for that and opens forwarding only when the policy is `DROP`.

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

**What you should see.** Each `docker pull` ends with `Status: Image is up to date` or `Downloaded`. The build ends with `orchestrator  Built` and `sysbench  Built`. `down` prints `Removed` for any old containers. The first time, it prints nothing much, because there is nothing to remove.

**How to check.** `docker image ls` includes `mysql`, `proxysql/proxysql`, `percona/percona-orchestrator`, and `alpine`. `docker ps -a --filter name=mysql-1` is empty.

## 2. Start the source and create the accounts

**What this does.** Starts only mysql-1. The image creates the data directory and the `root` account (`password mysql`, allowed from any host). Then it creates four accounts and the empty `sbtest` database.

**Why each account exists.**

| Account | Password | What it is for |
| --- | --- | --- |
| `repl` | `repl` | The replicas log in with this to pull changes. Privilege: `REPLICATION SLAVE`. |
| `orchestrator` | `orchestrator` | Orchestrator logs in with this to inspect replication and, during failover, to move a replica and clear `read_only`. It needs `SUPER`, replication-admin rights, and `SELECT` on `performance_schema` and on `mysql.slave_master_info` (Orchestrator still reads that table under the old name). |
| `monitor` | `monitor` | ProxySQL's health check. Privilege: `REPLICATION CLIENT`, so it can read `read_only`. It cannot change data. |
| `sbuser` | `sbpass` | The application. Rights only on `sbtest`. |

MySQL 8.4 turns the old password plugin off unless the server was started with `mysql_native_password=ON` (it is, in the cnf). ProxySQL 2.7.3 and this Orchestrator build log in with that plugin, so every account is created `IDENTIFIED WITH mysql_native_password`.

The wait is deliberately not `mysqladmin ping`. The image answers a ping from a temporary server, shuts that server down, and only then starts the real one. A command in that gap fails with `ERROR 2002`. The function waits for the log line `MySQL init process done. Ready for start up.` and then runs `SELECT 1`.

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

**What you should see.**

```text
== start the source and let the image initialise the datadir ==
mysql-1 is accepting connections
== create accounts on the source ==
mysql: [Warning] Using a password on the command line interface can be insecure.
```

The warning is MySQL complaining that the password is on the command line. The SQL itself is silent when it works. An `ERROR` line here means stop.

**How to check.** This asks MySQL who exists. The four accounts you just created use `mysql_native_password`. `root` stays on `caching_sha2_password`, which is the image default, and that is fine: you talk to `root` with the `mysql` client inside the container, not through ProxySQL. The `mysql.infoschema`, `mysql.session`, and `mysql.sys` rows are MySQL's own internal accounts.

```bash
docker exec mysql-1 mysql --protocol=socket -uroot -pmysql -e "SELECT User, Host, plugin FROM mysql.user ORDER BY User"
```

## 3. Copy the source's data onto the two replicas

**What this does.** Creates the replica containers so Compose owns their volumes, stops mysql-1, and copies its data directory onto both replica volumes. Deletes `auto.cnf` on the copies.

**Why.** If you start mysql-2 and mysql-3 empty, each one bootstraps its own GTID history. They would not be copies of mysql-1, and Orchestrator would refuse to promote them later. Copying the files keeps the GTID set identical. Deleting `auto.cnf` makes each replica invent a new server UUID on the next start, while the copied GTID history stays. `server_id` (1, 2, and 3) stays in each config file and is not inside this copy. Two servers must not share a server UUID.

`server_id` and `report_host` live in the config file, which is different per container, so the copy does not make mysql-2 think its name is mysql-1.

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

**What you should see.** Compose creates `mysql-2` and `mysql-3` and stops mysql-1. The two `docker run` copies print nothing when they succeed.

**How to check.** The proof is the next step's UUID lines: one shared GTID set, three different server UUIDs. If you look now, mysql-1 is stopped (`docker ps -a` shows `Exited`) and the other two exist but are not started.

## 4. Start all three and attach replication

**What this does.** Starts mysql-1, mysql-2, and mysql-3. Prints each server's UUID, GTID set, name, and read-only flags. Tells mysql-2 and mysql-3 to copy from mysql-1 using GTIDs (`SOURCE_AUTO_POSITION=1`), and waits until both the receiver and the applier are `ON`.

**Why.** `SOURCE_AUTO_POSITION=1` means "send me every GTID I do not already have". `SOURCE_CONNECT_RETRY=1` makes a disconnected replica try again every second, so a short blip does not leave it idle for the default 60 seconds. The retry count is large so a stopped source does not make the replica give up while you are still experimenting.

MySQL 8.4 removed `CHANGE MASTER TO`. The statement below is the current one.

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

**What you should see.** Three lines, then both replicas applying. From the clean run (your UUIDs will be different; the GTID set on all three lines must be the same, and it is only the bootstrap transactions, `:1-16`, because sysbench has not run yet):

```text
e77b6306-cb5c-11f1-8842-d21221edcaee  e77b6306-cb5c-11f1-8842-d21221edcaee:1-16  mysql-1  0  0
ed1d1c8b-cb5c-11f1-84b9-1a9293208783  e77b6306-cb5c-11f1-8842-d21221edcaee:1-16  mysql-2  1  1
ed1e3cd1-cb5c-11f1-b55e-4af5e88734d7  e77b6306-cb5c-11f1-8842-d21221edcaee:1-16  mysql-3  1  1
mysql-2 receiver=ON applier=ON
mysql-3 receiver=ON applier=ON
```

Read the columns as: server UUID, GTID set, `report_host`, `read_only`, `super_read_only`. mysql-1 is writable (`0 0`). Both replicas are read-only (`1 1`). The GTID UUID is mysql-1's UUID on every line. The server UUID on the replica lines is a different value, which is what deleting `auto.cnf` did.

**How to check.** On a replica, the human-readable status. `Source_Host` is `mysql-1`, both `Running` columns are `Yes`, `Auto_Position` is `1`.

```bash
docker exec mysql-2 mysql --protocol=socket -uroot -pmysql -e "SHOW REPLICA STATUS\G" | grep -E "Source_Host|Replica_IO_Running|Replica_SQL_Running|Auto_Position|Seconds_Behind"
```

A screenshot of this command on a healthy cluster is in the [README](../README.md#a-healthy-cluster). `Connecting` with error 110 is the firewall problem in the troubleshooting table, not a wrong password.

## 5. Put ProxySQL in front

**What this does.** Starts ProxySQL and registers all three servers in hostgroup 10. Adds one replication-hostgroup row: "check `read_only`; writers live in 10, readers live in 20." Creates the application user `sbuser`, aimed at hostgroup 10, with transactions pinned to the server they started on. Loads the config into the running process and saves it.

**Why.** The application will use one address (ProxySQL port 6033). The monitor then moves mysql-2 and mysql-3 to hostgroup 20 because they answer `read_only=1`. mysql-1 stays in hostgroup 10 because it answers `0`. You insert everyone into 10 first so the monitor has something to sort; you do not insert the replicas straight into 20, because a future promotion has to be able to find them from the writer list.

`transaction_persistent=1` is what keeps a transaction on one server. It is also why a later `SELECT` rule will not pull reads out of `oltp_read_write`. That experiment is in the README, and it needs a second client that does not open a transaction.

`LOAD MYSQL SERVERS TO RUNTIME` is the moment the change becomes real. Until that statement, the `INSERT` is only a saved row.

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
```

**What you should see.** The admin port comes up (`proxysql admin is up`). The loop prints the runtime table once a second. An early print can still show all three servers in hostgroup 10, which means the monitor has not sorted them yet. The loop stops when the check matches, and then prints `ProxySQL placement ok`. You may see the sorted table more than once; the `ok` line is the one that counts. It looks like this:

```text
hostgroup_id  hostname  status
10            mysql-1   ONLINE
20            mysql-2   ONLINE
20            mysql-3   ONLINE
ProxySQL placement ok
```

**How to check.** That table is the check. One `ONLINE` server in hostgroup 10, and it is mysql-1. Two `ONLINE` servers in hostgroup 20, mysql-2 and mysql-3. Anything `SHUNNED` at this point means the monitor cannot reach that server: see the troubleshooting table (firewall, or the server is still starting).

The web page, once you want it: `https://127.0.0.1:16080/`, user `stats`, password `stats`. It draws connection graphs. The table above is the hostgroup status.

## 6. Let Orchestrator discover the topology

**What this does.** Starts Orchestrator, asks it to look at mysql-1, and waits until it has found 3 servers.

**Why.** Orchestrator learns the replicas by asking the source who is connected (`DiscoverByShowSlaveHosts`, which still uses the historical name). Giving it mysql-1 is enough. It logs in as `orchestrator` / `orchestrator`.

The config prefers mysql-2 as the next source, accepts mysql-3, and refuses anyone else. Automatic recovery is on (`RecoverMasterClusterFilters` matches every cluster). After a promotion it runs `proxysql-failover-hook.sh`, which edits ProxySQL. There is no ProxySQL button inside Orchestrator 3.2.6; the hook is how you extend it.

The poll is every 2 seconds so a crash shows up quickly. That is a lab choice. Production is usually slower, and the failover time in the README belongs to these settings.

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

**What you should see.** `orchestrator http is up`, a long JSON document from the discover call (`"Code":"OK"`), then a count that climbs:

```text
orchestrator instances=1
orchestrator instances=1
orchestrator instances=3
```

`1` is normal for the first few seconds: Orchestrator has seen mysql-1 and has not walked to the replicas yet. It must reach `3` before you continue. The script exits if it does not.

**How to check.** Open `http://127.0.0.1:13000/` and open the cluster `mysql-1`. You should see mysql-1 at the top, read/write, with mysql-2 and mysql-3 under it, read-only. That picture is the first screenshot in the README. `/api/instances` returns 404 on this build; the count above comes from `/api/clusters-info`, which is the working endpoint.

## 7. Load data and start the application

**What this does.** sysbench creates 4 tables of 10 000 rows in `sbtest`, through ProxySQL, as `sbuser`. Those writes land on mysql-1 and replicate. Then a container starts `oltp_read_write` forever, 4 threads, one status line per second, with errors counted rather than fatal.

**Why the flags.** `--mysql-ignore-errors=all` keeps the process alive across a failover so you can see `err/s` rise and fall. `--db-ps-mode=disable` sends the statement text, which is what a ProxySQL query rule matches. The clock prefix on each line is there so you can line the output up with `docker kill`.

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

**What you should see.** sysbench prepare names the tables and the row counts:

```text
sysbench 1.0.20 (using system LuaJIT 2.1.0-beta3)
Creating table 'sbtest1'...
Inserting 10000 records into 'sbtest1'
Creating a secondary index on 'sbtest1'...
```

The same three lines appear for `sbtest2`, `sbtest3`, and `sbtest4`. Then the long-running container starts, and the script prints the addresses:

```text
ProxySQL MySQL   127.0.0.1:16033   sbuser / sbpass
ProxySQL admin   127.0.0.1:16032   admin / admin
ProxySQL web     https://127.0.0.1:16080/   stats / stats (digest)
Orchestrator     http://127.0.0.1:13000/
MySQL source     127.0.0.1:13316   root / mysql
MySQL replicas   127.0.0.1:13317 and 127.0.0.1:13318
```

**How to check.** `docker logs --tail 5 sysbench` shows a line every second. A healthy line has `thds: 4`, `err/s: 0.00`, `reconn/s: 0.00`, and `tps` in the hundreds. The column-by-column reading is in the README. Your `tps` will not match the write-up's 800; compare a failure to the lines just before it.

The replicas now have more GTIDs than `:1-16`. That is sysbench. Both `receiver` and `applier` should still be `ON`, and `Seconds_Behind_Source` should be a small number (0 or 1) once the burst of inserts has been applied.

## 8. Confirm the whole starting state

**What this does.** Runs `scripts/verify.sh`.

**Why.** It checks the five facts the experiments assume: mysql-1 answers, both replicas are `super_read_only` and applying, ProxySQL's only online writer is mysql-1, Orchestrator knows 3 servers, and sysbench is running.

```bash
./scripts/lab.sh verify
```

**What you should see.**

```text
verify: steady state ok
```

**How to check.** That line is the check. Any `verify:` message on stderr names the fact that failed. After you kill mysql-1 in experiment A, this command fails on purpose, because the writer is no longer mysql-1. Run it now, before you break anything.

You are ready for the experiments in the [README](../README.md#experiment-a-the-source-dies).

## Clean up

**What this does.** Deletes the lab containers, the data volumes, and the `mysql-ha` network.

**Why.** The volumes hold the MySQL files. Leaving them means the next run clones stale data. `-v` removes them.

```bash
./scripts/lab.sh teardown
```

**What you should see.** `Stopped`, `Removed`, and at the end `lab removed`.

**How to check.** `docker ps -a --filter network=mysql-ha` is empty, and `docker volume ls | grep mysql-async-ha` prints nothing.

This does not put your firewall back. If step 1 printed that it changed `iptables-legacy` FORWARD to `ACCEPT`, that change is still on the host. A sysbench container you started yourself for experiment C is not part of Compose; remove it with `docker rm -f` and the name you gave it.
