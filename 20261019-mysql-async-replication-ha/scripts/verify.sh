#!/usr/bin/env bash
# Assert the steady state the deploy script is supposed to reach.
set -euo pipefail

fail() { echo "verify: $*" >&2; exit 1; }

docker exec mysql-1 mysql --protocol=socket -uroot -pmysql -N -e "SELECT 1" >/dev/null \
    || fail "mysql-1 is not up"
docker exec mysql-2 mysql --protocol=socket -uroot -pmysql -N -e "SELECT @@global.super_read_only" | grep -qx 1 \
    || fail "mysql-2 is not super_read_only"
docker exec mysql-3 mysql --protocol=socket -uroot -pmysql -N -e "SELECT @@global.super_read_only" | grep -qx 1 \
    || fail "mysql-3 is not super_read_only"

for replica in mysql-2 mysql-3; do
    state="$(docker exec "$replica" mysql --protocol=socket -uroot -pmysql -N -e \
        "SELECT SERVICE_STATE FROM performance_schema.replication_connection_status WHERE CHANNEL_NAME='';
         SELECT IFNULL(
             (SELECT SERVICE_STATE FROM performance_schema.replication_applier_status_by_coordinator WHERE CHANNEL_NAME='' LIMIT 1),
             (SELECT SERVICE_STATE FROM performance_schema.replication_applier_status WHERE CHANNEL_NAME='' LIMIT 1)
         );")"
    io="$(printf '%s\n' "$state" | sed -n '1p')"
    sql="$(printf '%s\n' "$state" | sed -n '2p')"
    [ "$io" = "ON" ] && [ "$sql" = "ON" ] || fail "$replica replication is receiver=$io applier=$sql"
done

writer="$(docker exec proxysql mysql --protocol=tcp -N -h127.0.0.1 -P6032 -uadmin -padmin -e \
    "SELECT hostname FROM runtime_mysql_servers WHERE hostgroup_id=10 AND status='ONLINE'")"
[ "$writer" = "mysql-1" ] || fail "writer hostgroup is '$writer', expected mysql-1"

count="$(curl -sf http://127.0.0.1:13000/api/clusters-info | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["CountInstances"] if d else 0)')"
[ "$count" = "3" ] || fail "orchestrator knows $count instances, expected 3"

docker ps --format '{{.Names}}' | grep -qx sysbench || fail "sysbench container is not running"
echo "verify: steady state ok"
