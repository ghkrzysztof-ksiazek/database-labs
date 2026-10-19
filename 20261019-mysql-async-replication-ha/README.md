# High availability for MySQL asynchronous replication

**Krzysztof Książek**, senior MySQL DBRE (ex-Severalnines, ex-Pythian).

One MySQL 8.4 source, two replicas, GTID asynchronous replication, ProxySQL in front of the application, Orchestrator for automated master failover, and sysbench `oltp_read_write` through ProxySQL. The lab runs on a single Docker host. Passwords are plain text, TLS is off, and the failure detector is tuned so a crash is visible in one poll. It is a lab.

The measured run is 2026-10-19. Commands, timings, and screenshots below are from that run.

## Topology

```
sysbench oltp_read_write
        |
        |  6033
        v
    ProxySQL 2.7.3          web UI https://:6080  (stats/stats, digest)
    HG 10 writer
    HG 20 readers
        |
        +-- mysql-1   source     server_id 1   read_only=0     :13316
        +-- mysql-2   replica    server_id 2   super_read_only :13317
        +-- mysql-3   replica    server_id 3   super_read_only :13318
                ^
                |
        Orchestrator 3.2.6-24 (Percona)   http://:13000
        PostMasterFailoverProcesses -> proxysql-failover-hook.sh
```

| Piece | Choice |
| --- | --- |
| MySQL | Official `mysql:8.4.11`. GTID, `binlog_format=ROW`, `log_replica_updates`, `relay_log_recovery` |
| ProxySQL | `proxysql/proxysql:2.7.3`. Writer hostgroup 10, reader hostgroup 20, `check_type=read_only` |
| Orchestrator | `percona/percona-orchestrator:3.2.6-24`. Automatic master recovery, hook updates ProxySQL |
| Traffic | sysbench 1.0.20, `oltp_read_write`, 4 threads, 4 tables × 10 000 rows, through ProxySQL |

MySQL 8.4 removed `CHANGE MASTER TO`, `START SLAVE`, and `SHOW SLAVE STATUS`. The lab uses `CHANGE REPLICATION SOURCE TO` and `SHOW REPLICA STATUS`. Upstream openark Orchestrator 3.2.6 still emits the removed syntax, so discovery against 8.4 fails. The Percona build speaks 8.4.

Orchestrator 3.2.6 has no ProxySQL hostgroup driver. Steady state is ProxySQL's `read_only` monitor: a server with `read_only=0` stays in hostgroup 10, a server with `read_only=1` is moved to hostgroup 20. The hook (`docker/orchestrator/proxysql-failover-hook.sh`) runs from `PostMasterFailoverProcesses` after Orchestrator has already cleared `read_only` on the successor and repointed the other replica. The hook fences the failed hostname into hostgroup 30 as `OFFLINE_HARD` and inserts the successor into hostgroup 10 in the same second. What the runtime table keeps after that is measured in experiment A.

## Quick start

From this directory:

```bash
./scripts/lab.sh deploy
./scripts/lab.sh verify
./scripts/lab.sh teardown
```

`make deploy`, `make verify`, and `make teardown` call the same scripts. The deploy script and the hand-written procedure are the same steps. The hand-written procedure, including every grant and every admin statement, is [docs/manual-setup.md](docs/manual-setup.md).

## Ports and accounts

Host ports sit above the other labs in this repository (3307, 3000, 3001, 9090, 9091).

| Service | Host address | Account |
| --- | --- | --- |
| ProxySQL MySQL | `127.0.0.1:16033` | `sbuser` / `sbpass` |
| ProxySQL admin | `127.0.0.1:16032` | `admin` / `admin` |
| ProxySQL web | `https://127.0.0.1:16080/` | `stats` / `stats`, HTTP digest |
| Orchestrator | `http://127.0.0.1:13000/` | none (`AuthenticationMethod` empty, `PowerAuthUsers` `["*"]`) |
| mysql-1 | `127.0.0.1:13316` | `root` / `mysql` |
| mysql-2 | `127.0.0.1:13317` | `root` / `mysql` |
| mysql-3 | `127.0.0.1:13318` | `root` / `mysql` |

Other accounts, all `mysql_native_password`: `repl`/`repl` (`REPLICATION SLAVE`), `orchestrator`/`orchestrator` (topology user: `SUPER`, `REPLICATION_SLAVE_ADMIN`, `SYSTEM_VARIABLES_ADMIN`, `SELECT` on `performance_schema` and `mysql.slave_master_info`), `monitor`/`monitor` (`REPLICATION CLIENT`).

The web UI is HTTPS only. HTTP on 6080 returns an empty reply. The digest realm is `Access to ProxySQL status page`. `admin`/`admin` is the admin port, not the web UI.

The bundled ProxySQL pages are Home, System, MySQL connection graphs, and Query Cache. Hostgroup membership and query-rule hits are admin SQL (`runtime_mysql_servers`, `stats_mysql_query_rules`). Those are the terminal screenshots. `stats_mysql_query_rules` has two columns, `rule_id` and `hits`.

## How the datadir is cloned

Each server's `server_id` and `report_host` live in its cnf, not in the datadir. The source is initialised by the official entrypoint. The replica volumes are then a byte copy of that datadir with `auto.cnf` removed, so each replica generates its own `server_uuid` and keeps the source's `gtid_executed`. On the measured build the shared set was `0167371c-cb59-11f1-b4b1-3e1cd182c3ec:1-16` before sysbench, and the three UUIDs differed. Replicas attach with `SOURCE_AUTO_POSITION=1`.

`read_only` and `super_read_only` on a promoted replica are cleared in memory. The replica cnf still says `ON`. A later container restart of the new primary comes back read-only until someone clears the globals. Orchestrator does not rewrite the cnf.

The failure timings below are from the first stack. A later clean run of [docs/manual-setup.md](docs/manual-setup.md), on an empty volume, reproduced the steady state and was then torn down. All three servers printed `gtid_executed = e77b6306-cb5c-11f1-8842-d21221edcaee:1-16` with three different `server_uuid` values. Both replicas were `read_only=1` and `super_read_only=1`. ProxySQL moved mysql-2 and mysql-3 into hostgroup 20 on the second monitor pass. Orchestrator reported `CountInstances=3`. `./scripts/lab.sh verify` printed `verify: steady state ok`.

## Experiments

Traffic for A and B is the compose `sysbench` service: `oltp_read_write`, 4 threads, `--report-interval=1`, `--mysql-ignore-errors=all`, `--db-ps-mode=disable`, text protocol, through `proxysql:6033`. Lines are prefixed with `HH:MM:SS`. Baseline on this host was about 770–900 transactions/s, `err/s` 0, p95 latency about 7 ms. One steady line:

```text
01:15:39 [ 582s ] thds: 4 tps: 871.04 qps: 17399.82 (r/w/o: 12178.57/3479.16/1742.08) lat (ms,95%): 6.91 err/s: 0.00 reconn/s: 0.00
```

`transaction_persistent=1` pins each `BEGIN` … `COMMIT` to hostgroup 10, so this workload never reads from hostgroup 20. That is intentional for A and B, and it is why C uses a second sysbench.

Screenshots were taken from the running containers: Playwright against the Orchestrator UI and against the ProxySQL UI through a local digest proxy (the stock UI replies with no `Content-Type`, which Chromium treats as a download), and `ffmpeg -f x11grab` of an xterm on Xvfb for the SQL.

### Before any failure

Orchestrator, cluster alias `mysql-1`, both replicas replicating, about 1 s of lag, GTID, read-only:

![Orchestrator topology before failover](screenshots/orchestrator-topology-before.png)

`SHOW REPLICA STATUS` on mysql-2. `Source_Host=mysql-1`, both threads `Yes`, `Auto_Position=1`, `Replica_SQL_Running_State` waiting for an event:

![Replica status before failover](screenshots/mysql-replica-status-before.png)

`performance_schema.replication_connection_status` / `replication_applier_status_by_coordinator` are `ON`, and `SHOW REPLICAS` on the source lists mysql-2 and mysql-3:

![SHOW REPLICAS before failover](screenshots/mysql-show-replicas-before.png)

ProxySQL runtime: mysql-1 `ONLINE` in hostgroup 10, mysql-2 and mysql-3 `ONLINE` in hostgroup 20.

![ProxySQL servers before failover](screenshots/proxysql-servers-before.png)

ProxySQL's own UI at the same time. The MySQL page is connection-pool history (client connections and server connections, about four backend connections), not a hostgroup table:

![ProxySQL connection graphs before failover](screenshots/proxysql-connections-before.png)

![ProxySQL home before failover](screenshots/proxysql-home-before.png)

### A. Source failure

`docker kill mysql-1` at 01:18:57, under the `oltp_read_write` load. No restart policy, so the container stayed `Exited (137)`.

Orchestrator's cluster view, one line per second (`/api/topology` compressed the same way the UI does):

```text
01:18:57 mysql-1 [0s,ok,rw]  + mysql-2 [1s,ok,ro]  + mysql-3 [1s,ok,ro]
01:18:58 mysql-1 [unknown,invalid,rw]  - mysql-2 [null,nonreplicating,ro]  - mysql-3 [null,nonreplicating,ro]
01:18:59 mysql-2 [0s,ok,rw]  + mysql-3 [0s,ok,ro]
```

The hook log is the same second as the promotion:

```text
2026-10-19T01:18:59+00:00 detected DeadMaster cluster=mysql-1:3306 failed=mysql-1:3306
2026-10-19T01:18:59+00:00 pre-failover DeadMaster cluster=mysql-1:3306 failed=mysql-1:3306
2026-10-19T01:18:59+00:00 hook start type=DeadMaster failed=mysql-1 successor=mysql-2
2026-10-19T01:18:59+00:00 fenced mysql-1 into hostgroup 30
2026-10-19T01:18:59+00:00 successor mysql-2 read_only=0
2026-10-19T01:18:59+00:00 published mysql-2 into writer hostgroup 10
2026-10-19T01:18:59+00:00 post-failover DeadMaster failed=mysql-1 successor=mysql-2:3306
```

`InstancePollSeconds=2` and `MySQLConnectTimeoutSeconds=1`, so detection plus promotion was one poll: the kill second still showed the old primary, the next second showed it invalid, the second after that showed mysql-2 writable and mysql-3 applying from it with 0 s of lag. `DetectPromotionRuleQuery` prefers mysql-2, which is why the successor was mysql-2 and not mysql-3.

sysbench, same clock:

```text
01:18:56 [ 779s ] thds: 4 tps: 888.31 qps: 17773.22 (r/w/o: 12436.36/3560.24/1776.62) lat (ms,95%): 6.67 err/s: 0.00 reconn/s: 0.00
01:18:57 [ 780s ] thds: 4 tps: 430.32 qps: 8597.38 (r/w/o: 6022.47/1714.27/860.64) lat (ms,95%): 9.73 err/s: 0.00 reconn/s: 4.00
01:18:58 [ 781s ] thds: 4 tps: 0.00   qps: 0.00    (r/w/o: 0.00/0.00/0.00)       lat (ms,95%): 0.00 err/s: 0.00 reconn/s: 0.00
01:18:59 [ 782s ] thds: 4 tps: 0.00   qps: 0.00    (r/w/o: 0.00/0.00/0.00)       lat (ms,95%): 0.00 err/s: 4.00 reconn/s: 0.00
01:19:00 [ 783s ] thds: 4 tps: 522.99 qps: 10481.76 (r/w/o: 7337.83/2095.95/1047.98) lat (ms,95%): 4.91 err/s: 0.00 reconn/s: 0.00
01:19:01 [ 784s ] thds: 4 tps: 760.13 qps: 15241.48 (r/w/o: 10674.73/3044.50/1522.25) lat (ms,95%): 5.09 err/s: 2.00 reconn/s: 0.00
01:19:02 [ 785s ] thds: 4 tps: 1021.94 qps: 20420.83 (r/w/o: 14289.17/4087.77/2043.88) lat (ms,95%): 5.67 err/s: 0.00 reconn/s: 0.00
```

The application-visible stall is the two zero-TPS seconds, 01:18:58 and 01:18:59. Throughput is back in the following second (523 tps) and above the baseline the second after that. `reconn/s` 4.00 on the kill second is one reconnect per thread. `err/s` 4.00 on 01:18:59 is one error per thread (`--mysql-ignore-errors=all` counts them and continues). Two more errors land at 01:19:01 (`err/s` 2.00) from threads whose next statement still hit a dead backend; after that `err/s` is 0.

ProxySQL after the hook. mysql-2 is `ONLINE` in hostgroup 10. mysql-1 is `SHUNNED` in hostgroup 10, not `OFFLINE_HARD` in hostgroup 30. mysql-3 was `SHUNNED` in hostgroup 20 for this sample even though its replication threads were already `Yes`; a later `LOAD MYSQL SERVERS TO RUNTIME` returned it to `ONLINE`.

![ProxySQL servers after failover](screenshots/proxysql-servers-after.png)

The monitor shuns a backend after missed pings (`shun_on_failures=2`, ping every 1000 ms). `docker kill` also deletes the container's DNS record. The monitor then logs `Unknown server host 'mysql-1' (-2)` and, once heartbeats are missed, `missed 3 heartbeats, shunning it`. A shunned server is not used, so the dead primary took no further writes. The hook did execute the hostgroup-30 insert (the log line is from the hook, after `LOAD MYSQL SERVERS`), and a later manual re-fence left `mysql-1` / `OFFLINE_HARD` / hostgroup 30 in the *config* table. Runtime did not keep that row: ProxySQL drops a server whose name no longer resolves when it rebuilds runtime. The fence that survives a `docker kill` is the shun, plus the fact the process is gone. A partition where the old primary still resolves and still accepts connections was not this experiment; the hook's `OFFLINE_HARD` insert is aimed at that case, and this run did not prove the row sticks across a monitor commit while DNS still works.

Orchestrator after promotion. Alias is now `mysql-2`. mysql-3 replicates from it. mysql-1 is listed as an invalid last check, still tagged read/write because the server never answered a `read_only` query after the kill:

![Orchestrator topology after failover](screenshots/orchestrator-topology-after.png)

![Orchestrator cluster list after failover](screenshots/orchestrator-clusters-after.png)

mysql-2 has an empty `SHOW REPLICA STATUS` (it is the writer; `read_only=0`, `super_read_only=0`). mysql-3 has `Source_Host=mysql-2`, `Replica_IO_Running=Yes`, `Replica_SQL_Running=Yes`, `Seconds_Behind_Source=1`, `Auto_Position=1`, `Source_Server_Id=2`. `Retrieved_Gtid_Set` is the new primary's UUID `084bc058-cb59-11f1-a48c-ae0ad6aeb9fd:1-2912`. `Executed_Gtid_Set` still contains the old source `0167371c-cb59-11f1-b4b1-3e1cd182c3ec:1-659315` plus the new primary's transactions. Orchestrator repointed the surviving replica with `SOURCE_AUTO_POSITION=1`; it did not rebuild mysql-1.

![Replica status after failover](screenshots/mysql-replica-status-after.png)

`SHOW REPLICAS` on mysql-2 lists mysql-3. The applier on mysql-3 is `ON`. mysql-1 is not a replica of anything.

![SHOW REPLICAS after failover](screenshots/mysql-show-replicas-after.png)

ProxySQL's connection graph across the same window. Client connections stay up (sysbench reconnects into the pool); server connections dip and return:

![ProxySQL connection graphs after failover](screenshots/proxysql-connections-after.png)

Async replication can lose commits that were on mysql-1 and not yet applied. The killed datadir was not reopened, so that gap was not counted. `Executed_Gtid_Set` on the new primary at promotion contained the old source through transaction 659315. Anything mysql-1 committed after the replicas had applied that GTID is gone. `sync_binlog=1` and `innodb_flush_log_at_trx_commit=1` are set; they do not close an apply lag.

`FailureDetectionPeriodBlockMinutes=1` blocks a second automatic recovery for one minute. Experiment C finished, the replicas were restarted, and this kill waited that block out.

### B. One replica dies, application still on the writer

`docker kill mysql-3` at 01:16:02, before any query rule. Every `oltp_read_write` transaction is pinned to hostgroup 10.

```text
01:16:02 [ 605s ] thds: 4 tps: 855.82 qps: 17099.32 err/s: 0.00 reconn/s: 0.00
01:16:03 [ 606s ] thds: 4 tps: 1066.98 qps: 21339.67 err/s: 0.00 reconn/s: 0.00
01:16:09 [ 612s ] thds: 4 tps: 809.31 qps: 16152.09 err/s: 0.00 reconn/s: 0.00
```

`err/s` stayed 0 and `reconn/s` stayed 0 through the kill and through the following minute, including after `docker start mysql-3`. The application never used mysql-3.

ProxySQL moved nothing the application was using. mysql-3 went `SHUNNED` in hostgroup 20. mysql-1 stayed `ONLINE` in hostgroup 10. mysql-2 stayed `ONLINE` in hostgroup 20.

![ProxySQL servers after replica kill](screenshots/proxysql-servers-replica-down.png)

The connect-log sample taken in the same few seconds still showed the previous successful connects (success times 0.4–2 ms, `connect_error` NULL). The error row for this hostname showed up on the next kill of the same container, in experiment C: `connect_success_time_us=0`, `connect_error=Unknown server host 'mysql-3' (-2)`. That is the monitor's view of a `docker kill`: the DNS name is gone, the connect fails, the ping check shuns the server. The connection graph barely moves, because the writer pool is untouched:

![ProxySQL connections while a reader is down](screenshots/proxysql-connections-replica-down.png)

After `docker start mysql-3` the replication receiver was `ON` within a few seconds. ProxySQL left the server `SHUNNED` for longer than `shun_recovery_time_sec=10` in that window. A `LOAD MYSQL SERVERS TO RUNTIME` put it back to `ONLINE`. The application did not have to wait for that.

### C. Route autocommit SELECTs to the readers, then lose the readers

The rule:

```sql
DELETE FROM mysql_query_rules;
INSERT INTO mysql_query_rules (rule_id, active, match_digest, destination_hostgroup, apply, comment)
VALUES (1, 1, '^SELECT', 20, 1, 'reads to reader hostgroup');
LOAD MYSQL QUERY RULES TO RUNTIME;
```

![Query rule inserted](screenshots/proxysql-query-rules.png)

`oltp_read_write` kept running and kept succeeding (`err/s` 0, roughly 640–1000 tps depending on how busy the readers were). Its statements run inside `BEGIN`, the first statement of the session hits the default hostgroup, and `transaction_persistent=1` pins the rest of the transaction there. The `^SELECT` rule does not steal those reads. Digest totals from the admin database confirm the split that *did* happen: hostgroup 10 had about 14.4 million calls (the read/write workload) and hostgroup 20 had 215 182 calls (the autocommit read workload) before the readers were killed.

The read workload is a second container:

```bash
sysbench /usr/share/sysbench/oltp_read_only.lua \
  --db-driver=mysql --mysql-host=proxysql --mysql-port=6033 \
  --mysql-user=sbuser --mysql-password=sbpass --mysql-db=sbtest \
  --tables=4 --table-size=10000 --threads=2 --time=0 \
  --report-interval=1 --mysql-ignore-errors=all \
  --db-ps-mode=disable --skip-trx=on \
  run
```

`--skip-trx=on` is the part that lets the rule match. `--db-ps-mode=disable` keeps the statement text visible to `match_digest`.

Baseline for that client was about 520–640 tps, reads only, `err/s` 0. `stats_mysql_query_rules` showed the rule taking the traffic (`rule_id` 1, hits climbing; a later sample in this same session was 169 881 hits after a few seconds and 668 142 hits after the fallback below).

**One reader down.** `docker kill mysql-3` at 01:17:02.

```text
01:17:02 [ 10s ] thds: 2 tps: 579.99 qps: 8121.88 err/s: 0.00 reconn/s: 0.00
01:17:03 [ 11s ] thds: 2 tps: 820.61 qps: 11490.60 err/s: 1.00 reconn/s: 0.00
01:17:04 [ 12s ] thds: 2 tps: 731.40 qps: 10249.63 err/s: 0.00 reconn/s: 0.00
```

One second records `err/s` 1.00 (one of the two threads hit the dead replica). From the next second, reads run on the remaining reader, mysql-2, at about 730–820 tps, `err/s` 0. The write workload stays on mysql-1 with `err/s` 0. Runtime at that point:

![One reader shunned](screenshots/proxysql-servers-one-reader-down.png)

**Both readers down, no fallback.** `docker kill mysql-2` at 01:17:14. Hostgroup 20 has no `ONLINE` server. `mysql-monitor_writer_is_also_reader` is false, and the writer was not inserted into hostgroup 20.

```text
01:17:14 [ 22s ] thds: 2 tps: 912.90 qps: 12775.59 err/s: 0.00
01:17:15 [ 23s ] thds: 2 tps: 266.83 qps: 3741.59  err/s: 0.00
01:17:16 [ 24s ] thds: 2 tps: 0.00   qps: 0.00     err/s: 2.00
01:17:17 [ 25s ] thds: 2 tps: 0.00   qps: 0.00     err/s: 0.00
01:17:18 [ 26s ] thds: 2 tps: 0.00   qps: 0.00     err/s: 2.00
```

Reads stop. `err/s` alternates 2.00 and 0.00: two threads, each failing on the connect timeout and then waiting. That pattern continued for as long as hostgroup 20 had only `SHUNNED` servers. The write workload, still pinned to hostgroup 10, did not notice:

```text
01:17:17 [ 680s ] thds: 4 tps: 1013.47 qps: 20281.40 err/s: 0.00 reconn/s: 0.00
01:17:22 [ 685s ] thds: 4 tps: 901.94  qps: 18028.73 err/s: 0.00 reconn/s: 0.00
```

**The global flag, on its own, does not add the writer to the reader hostgroup.** At 01:17:23 `mysql-monitor_writer_is_also_reader` was set to `true` and `LOAD MYSQL VARIABLES TO RUNTIME` was run. Four seconds later runtime was still:

```text
hostgroup_id  hostname  status
10            mysql-1   ONLINE
20            mysql-2   SHUNNED
20            mysql-3   SHUNNED
```

Reads stayed at 0 tps, `err/s` alternating 2 and 0, through 01:17:26. ProxySQL logged `read_only_action_v2() detected RO=0 on server mysql-1:3306 for the first time after commit(), but no need to reconfigure`.

That matches `read_only_action_v2` in ProxySQL 2.7.3 (`lib/MySQL_HostGroups_Manager.cpp`). For a server that is already a writer, the function only rewrites hostgroups when `read_only` has just changed to 0 *and* a reader-hostgroup copy is missing from the writer hostgroup. The `mysql-monitor_writer_is_also_reader` branch then decides whether to clear the reader copy. A server that has been `read_only=0` for a while hits the path "already detected as RO=0, no action". Setting the global does not copy it into hostgroup 20. The 2.7.3 `mysql_replication_hostgroups` table has nowhere to store a per-cluster `writer_is_also_reader` either; that column is on the group-replication and Galera tables.

**Fallback that does restore reads.** With the flag irrelevant to a stable writer, insert the current writer into the reader hostgroup:

```sql
INSERT INTO mysql_servers (hostgroup_id, hostname, port, max_connections, status, comment)
VALUES (20, 'mysql-2', 3306, 200, 'ONLINE', 'writer also reader');
LOAD MYSQL SERVERS TO RUNTIME;
SAVE MYSQL SERVERS TO DISK;
```

This was measured after failover, so the writer was mysql-2 and the only remaining reader was mysql-3. `docker kill mysql-3` at 01:23:33 dropped the read client to 0 tps (`err/s` 1.00, two threads). The insert ran at 01:23:40. The same second, reads resumed:

```text
01:23:33 [ 21s ] thds: 2 tps: 438.23 qps: 6156.28  err/s: 0.00
01:23:34 [ 22s ] thds: 2 tps: 0.00   qps: 0.00     err/s: 0.00
01:23:35 [ 23s ] thds: 2 tps: 0.00   qps: 0.00     err/s: 1.00
01:23:39 [ 27s ] thds: 2 tps: 0.00   qps: 0.00     err/s: 1.00
01:23:40 [ 28s ] thds: 2 tps: 635.37 qps: 8893.20  err/s: 0.00
01:23:41 [ 29s ] thds: 2 tps: 834.58 qps: 11686.17 err/s: 0.00
01:23:45 [ 33s ] thds: 2 tps: 888.99 qps: 12449.87 err/s: 0.00
```

Runtime kept the extra row. The monitor logged the same "no need to reconfigure" line and did not remove it. Setting the global back to `false` also did not remove it: once `read_only` has already been observed as 0, `read_only_action_v2` does not revisit the reader copy. The write workload stayed on hostgroup 10 at about 700–750 tps, `err/s` 0, while those reads were served by the same server via hostgroup 20.

![Writer present in both hostgroups, rule hits](screenshots/proxysql-writer-also-reader.png)

So, for this ProxySQL:

- With no ONLINE server in hostgroup 20, autocommit reads fail. They do not fall through to the user's default hostgroup.
- `mysql-monitor_writer_is_also_reader=true` does not populate hostgroup 20 from a writer that is already writable.
- An explicit `INSERT` of that writer into hostgroup 20 takes effect on `LOAD MYSQL SERVERS` and survives the monitor. Reads recover in the same second. The writer then takes read traffic as well as write traffic, which is the tradeoff (stale-read avoidance versus load on the primary).

The insert is a manual step in this lab. The failover hook does not add it, because the default workload does not read from hostgroup 20. If you add the `^SELECT` rule, add the current writer to hostgroup 20 as well, or accept that losing every replica fails reads while writes continue.

## Caveats

- Detection is lab-tuned: Orchestrator polls every 2 s with a 1 s connect timeout, ProxySQL pings every 1 s and shuns after 2 failures. A production Orchestrator poll is usually 5–10 s. The ~2 s promotion and the ~2 s zero-TPS window are this configuration.
- The promoted replica's `read_only` / `super_read_only` are memory-only. Restarting that container loads `read_only=ON` from its cnf.
- The old primary is not rebuilt as a replica. Bringing mysql-1 back means cloning again and pointing it at the new source. `must_not` on any host other than mysql-2 and mysql-3 stops Orchestrator preferring the old source if it reappears.
- `docker kill` removes DNS. The hostgroup-30 `OFFLINE_HARD` row is written and then dropped from runtime because the name does not resolve. The shun is what keeps the dead server out of the pool. A network partition in which the old primary still accepts writes was not measured.
- A restarted replica can stay `SHUNNED` longer than `shun_recovery_time_sec`. `LOAD MYSQL SERVERS TO RUNTIME` clears it once replication is up.
- ProxySQL and Orchestrator are single containers. Losing either one is not covered.
- MySQL 8.4 logs a warning that `binlog_format` is deprecated. The variable is still set to `ROW` so the replicas and Orchestrator agree on the format. The default is already `ROW`.
- The Docker host used for the run had `iptables-legacy` FORWARD policy DROP while Docker 29 programmed nftables. Container-to-container traffic timed out until `sudo iptables-legacy -P FORWARD ACCEPT`. `scripts/deploy.sh` does that only when the policy is DROP.

## Layout

```
docker/docker-compose.yml
docker/mysql/mysql-1.cnf
docker/mysql/mysql-2.cnf
docker/mysql/mysql-3.cnf
docker/proxysql/proxysql.cnf
docker/orchestrator/Dockerfile
docker/orchestrator/orchestrator.conf.json
docker/orchestrator/proxysql-failover-hook.sh
docker/sysbench/Dockerfile
scripts/deploy.sh
scripts/verify.sh
scripts/teardown.sh
scripts/lab.sh
docs/manual-setup.md
screenshots/
```

## This is a lab

Plain-text passwords, no TLS, a single Docker host, a 128 MB buffer pool, and a failure detector set to fire quickly. The shape is a source, two replicas, a proxy, and an external failover manager. The configuration is not something to copy onto production hardware.
