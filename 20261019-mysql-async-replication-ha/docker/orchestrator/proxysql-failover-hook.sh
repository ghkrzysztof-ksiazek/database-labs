#!/bin/sh
# Orchestrator PostMasterFailoverProcesses hook.
#
# Orchestrator 3.2.6 has no ProxySQL hostgroup driver. The supported extension
# point is this hook, which runs on the Orchestrator host after a successful
# master failover (ApplyMySQLPromotionAfterMasterFailover has already cleared
# read_only / super_read_only on the successor and repointed the other replica).
#
# Steady state is still ProxySQL's read_only monitor: it moves a server between
# writer hostgroup 10 and reader hostgroup 20. This hook only does what the
# monitor cannot do quickly or safely:
#   1. Fence the failed source into quarantine hostgroup 30 so a partitioned
#      but still-accepting primary cannot take another write.
#   2. Publish the successor into writer hostgroup 10 in the same second,
#      instead of waiting for the next read_only poll.
#
# Placeholders substituted by Orchestrator: failed host, successor host, type.
set -u

FAILED_HOST="${1:-}"
SUCCESSOR_HOST="${2:-}"
FAILURE_TYPE="${3:-unknown}"
LOG=/var/log/proxysql-failover.log
MYSQL="mysql --protocol=tcp --skip-ssl --connect-timeout=5 --batch --skip-column-names"

log() {
    printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"
}

log "hook start type=${FAILURE_TYPE} failed=${FAILED_HOST} successor=${SUCCESSOR_HOST}"

if [ -z "$FAILED_HOST" ]; then
    log "no failed host; nothing to fence"
    exit 0
fi

# Fence first, even if the successor is not ready yet.
$MYSQL -h proxysql -P 6032 -uadmin -padmin <<SQL
DELETE FROM mysql_servers WHERE hostname='${FAILED_HOST}';
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections, status, comment)
VALUES (30, '${FAILED_HOST}', 3306, 10, 'OFFLINE_HARD', 'fenced by orchestrator ${FAILURE_TYPE}');
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
SQL
log "fenced ${FAILED_HOST} into hostgroup 30"

if [ -z "$SUCCESSOR_HOST" ] || [ "$SUCCESSOR_HOST" = "$FAILED_HOST" ]; then
    log "no distinct successor; read_only monitor remains the reconciler"
    exit 0
fi

ready=0
i=0
while [ "$i" -lt 20 ]; do
    ro=$($MYSQL -h "$SUCCESSOR_HOST" -P 3306 -uorchestrator -porchestrator -e "SELECT @@global.read_only" 2>>"$LOG" || true)
    log "successor ${SUCCESSOR_HOST} read_only=${ro:-unknown}"
    if [ "$ro" = "0" ]; then
        ready=1
        break
    fi
    i=$((i + 1))
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    log "successor did not become writable; leaving hostgroup placement to the read_only monitor"
    exit 0
fi

$MYSQL -h proxysql -P 6032 -uadmin -padmin <<SQL
DELETE FROM mysql_servers WHERE hostname='${SUCCESSOR_HOST}';
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections, status, comment)
VALUES (10, '${SUCCESSOR_HOST}', 3306, 200, 'ONLINE', 'promoted by orchestrator');
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
SQL
log "published ${SUCCESSOR_HOST} into writer hostgroup 10"
exit 0
