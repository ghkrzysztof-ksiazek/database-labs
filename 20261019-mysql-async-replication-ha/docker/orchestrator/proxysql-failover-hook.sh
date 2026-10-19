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
# Not "admin": ProxySQL only accepts that user from its own localhost.
ADMIN="$MYSQL -h proxysql -P 6032 -uradmin -pradmin"

log() {
    printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"
}

log "hook start type=${FAILURE_TYPE} failed=${FAILED_HOST} successor=${SUCCESSOR_HOST}"

if [ -z "$FAILED_HOST" ]; then
    log "no failed host; nothing to fence"
    exit 0
fi

# Fence first, even if the successor is not ready yet.
# SAVE ... FROM RUNTIME first: the read_only monitor only changes the runtime,
# so the admin table still holds the deploy-time rows (every server in
# hostgroup 10). Loading those back would make the replicas writer targets
# until the next read_only check, and writes would fail on super_read_only.
if $ADMIN <<SQL 2>>"$LOG"
SAVE MYSQL SERVERS FROM RUNTIME;
DELETE FROM mysql_servers WHERE hostname='${FAILED_HOST}';
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections, status, comment)
VALUES (30, '${FAILED_HOST}', 3306, 10, 'OFFLINE_HARD', 'fenced by orchestrator ${FAILURE_TYPE}');
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
SQL
then
    log "fenced ${FAILED_HOST} into hostgroup 30"
else
    log "FAILED to fence ${FAILED_HOST}: ProxySQL admin statement failed"
fi

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

# No second SAVE FROM RUNTIME here: runtime_mysql_servers does not list
# OFFLINE_HARD rows, so it would drop the hostgroup 30 fence row.
if $ADMIN <<SQL 2>>"$LOG"
DELETE FROM mysql_servers WHERE hostname='${SUCCESSOR_HOST}';
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections, status, comment)
VALUES (10, '${SUCCESSOR_HOST}', 3306, 200, 'ONLINE', 'promoted by orchestrator');
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
SQL
then
    log "published ${SUCCESSOR_HOST} into writer hostgroup 10"
else
    log "FAILED to publish ${SUCCESSOR_HOST}: ProxySQL admin statement failed"
    exit 1
fi
exit 0
