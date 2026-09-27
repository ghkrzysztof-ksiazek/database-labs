"""Generate the ClickHouse server + Keeper Grafana dashboards (Prometheus only).

Writes clickhouse-server.json and clickhouse-keeper.json into the monitoring role;
ship them with `make deploy`, or without a Helm upgrade:
`cd ansible && ../.venv/bin/ansible-playbook playbooks/refresh-alerts.yml`.

    python3 scripts/gen-grafana-dashboards.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "ansible/roles/monitoring/files/dashboards"
DS = {"type": "prometheus", "uid": "${datasource}"}


class Board:
    def __init__(self):
        self.panels = []
        self.y = 0
        self.x = 0
        self.row_h = 0
        self.next_id = 1

    def _id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def row(self, title):
        self._newline()
        self.panels.append({"id": self._id(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def _newline(self):
        if self.x:
            self.y += self.row_h
            self.x = 0
            self.row_h = 0

    def _place(self, w, h):
        if self.x + w > 24:
            self._newline()
        pos = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.x += w
        self.row_h = max(self.row_h, h)
        return pos

    def add(self, ptype, title, targets, w=8, h=8, unit=None, desc=None, **extra):
        defaults = {"custom": {}}
        if unit:
            defaults["unit"] = unit
        if ptype == "timeseries":
            defaults["custom"] = {"lineWidth": 1, "fillOpacity": 10, "showPoints": "never", "spanNulls": True}
        defaults.update(extra.pop("defaults", {}))
        p = {
            "id": self._id(), "type": ptype, "title": title, "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": [dict({"datasource": DS, "refId": chr(65 + i)}, **t) for i, t in enumerate(targets)],
            "fieldConfig": {"defaults": defaults, "overrides": extra.pop("overrides", [])},
            "options": extra.pop("options", {}),
        }
        if ptype == "timeseries":
            p["options"] = {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]},
                            "tooltip": {"mode": "multi", "sort": "desc"}, **p["options"]}
        if desc:
            p["description"] = desc
        p.update(extra)
        self.panels.append(p)

    def ts(self, title, *targets, **kw):
        self.add("timeseries", title, [t if isinstance(t, dict) else {"expr": t[0], "legendFormat": t[1]} for t in targets], **kw)

    def stat(self, title, expr, legend="{{pod}}", w=4, h=4, **kw):
        kw.setdefault("options", {"colorMode": "background", "graphMode": "none", "textMode": "value_and_name",
                                  "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}})
        self.add("stat", title, [{"expr": expr, "legendFormat": legend, "instant": True}], w=w, h=h, **kw)

    def dashboard(self, uid, title, var_query, description, tags):
        return {
            "annotations": {"list": []}, "editable": True, "graphTooltip": 1, "id": None,
            "links": [{"type": "dashboards", "tags": ["clickhouse"], "asDropdown": True, "title": "ClickHouse dashboards"}],
            "panels": self.panels, "refresh": "30s", "schemaVersion": 39, "tags": tags,
            "templating": {"list": [
                {"name": "datasource", "label": "Datasource", "type": "datasource", "query": "prometheus",
                 "hide": 0, "current": {}},
                {"name": "pod", "label": "Pod", "type": "query", "datasource": DS,
                 "query": {"query": var_query, "refId": "pod"}, "definition": var_query,
                 "refresh": 2, "multi": True, "includeAll": True, "current": {"text": "All", "value": "$__all"},
                 "sort": 1},
            ]},
            "time": {"from": "now-1h", "to": "now"}, "timezone": "browser",
            "title": title, "uid": uid, "description": description, "version": 1,
        }


RED_GREEN = {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]}
GREEN_RED = lambda warn, crit: {"mode": "absolute", "steps": [  # noqa: E731
    {"color": "green", "value": None}, {"color": "orange", "value": warn}, {"color": "red", "value": crit}]}


def server():
    S = 'job="clickhouse-http", pod=~"$pod"'
    b = Board()
    b.row("Health")
    b.stat("Scrape up", f"up{{{S}}}", defaults={"thresholds": RED_GREEN,
           "mappings": [{"type": "value", "options": {"0": {"text": "DOWN"}, "1": {"text": "UP"}}}]})
    b.stat("Uptime", f"ClickHouseAsyncMetrics_Uptime{{{S}}}", unit="s", defaults={"color": {"mode": "fixed", "fixedColor": "blue"}})
    b.stat("Readonly replicas", f"ClickHouseMetrics_ReadonlyReplica{{{S}}}", defaults={"thresholds": GREEN_RED(1, 1)})
    b.stat("Max replica delay", f"ClickHouseAsyncMetrics_ReplicasMaxAbsoluteDelay{{{S}}}", unit="s",
           defaults={"thresholds": GREEN_RED(30, 300)})
    b.stat("Max parts / partition", f"ClickHouseAsyncMetrics_MaxPartCountForPartition{{{S}}}",
           defaults={"thresholds": GREEN_RED(300, 1000)},
           desc="Inserts are delayed at parts_to_delay_insert (1000) and rejected at parts_to_throw_insert (3000).")
    b.stat("Errors in range", f"sum by (pod) (increase(ClickHouseErrorMetric_ALL{{{S}}}[$__range]))",
           defaults={"thresholds": GREEN_RED(1, 10), "decimals": 0},
           desc="Increase of system.errors (all codes) over the selected time range.")

    b.row("Queries")
    b.ts("Queries started / s",
         (f"sum by (pod) (rate(ClickHouseProfileEvents_SelectQuery{{{S}}}[$__rate_interval]))", "SELECT {{pod}}"),
         (f"sum by (pod) (rate(ClickHouseProfileEvents_InsertQuery{{{S}}}[$__rate_interval]))", "INSERT {{pod}}"),
         (f"sum by (pod) (rate(ClickHouseProfileEvents_Query{{{S}}}[$__rate_interval]))", "all {{pod}}"),
         unit="reqps")
    b.ts("Failed queries / s",
         (f"sum by (pod) (rate(ClickHouseProfileEvents_FailedSelectQuery{{{S}}}[$__rate_interval]))", "SELECT {{pod}}"),
         (f"sum by (pod) (rate(ClickHouseProfileEvents_FailedInsertQuery{{{S}}}[$__rate_interval]))", "INSERT {{pod}}"),
         (f"sum by (pod) (rate(ClickHouseProfileEvents_FailedQuery{{{S}}}[$__rate_interval]))", "all {{pod}}"),
         unit="reqps", defaults={"color": {"mode": "palette-classic"}})
    b.ts("Average query duration",
         (f"rate(ClickHouseProfileEvents_SelectQueryTimeMicroseconds{{{S}}}[$__rate_interval]) / 1e6"
          f" / rate(ClickHouseProfileEvents_SelectQuery{{{S}}}[$__rate_interval])", "SELECT {{pod}}"),
         (f"rate(ClickHouseProfileEvents_InsertQueryTimeMicroseconds{{{S}}}[$__rate_interval]) / 1e6"
          f" / rate(ClickHouseProfileEvents_InsertQuery{{{S}}}[$__rate_interval])", "INSERT {{pod}}"),
         unit="s")
    b.ts("Running queries", (f"ClickHouseMetrics_Query{{{S}}}", "{{pod}}"), w=8)
    b.ts("Open connections",
         (f"ClickHouseMetrics_TCPConnection{{{S}}}", "native {{pod}}"),
         (f"ClickHouseMetrics_HTTPConnection{{{S}}}", "http {{pod}}"),
         (f"ClickHouseMetrics_InterserverConnection{{{S}}}", "interserver {{pod}}"), w=8)
    b.ts("Query memory (MemoryTracking)", (f"ClickHouseMetrics_MemoryTracking{{{S}}}", "{{pod}}"), unit="bytes", w=8)

    b.row("Reads and writes")
    b.ts("Rows inserted / s", (f"rate(ClickHouseProfileEvents_InsertedRows{{{S}}}[$__rate_interval])", "{{pod}}"), unit="rowsps")
    b.ts("Bytes inserted / s", (f"rate(ClickHouseProfileEvents_InsertedBytes{{{S}}}[$__rate_interval])", "{{pod}}"), unit="Bps")
    b.ts("Delayed / rejected inserts",
         (f"rate(ClickHouseProfileEvents_DelayedInserts{{{S}}}[$__rate_interval])", "delayed/s {{pod}}"),
         (f"rate(ClickHouseProfileEvents_RejectedInserts{{{S}}}[$__rate_interval])", "rejected/s {{pod}}"),
         (f"ClickHouseMetrics_DelayedInserts{{{S}}}", "delayed now {{pod}}"),
         desc="Non-zero means too many parts: merges can't keep up with the insert rate.")
    b.ts("Rows read / s", (f"rate(ClickHouseProfileEvents_SelectedRows{{{S}}}[$__rate_interval])", "{{pod}}"), unit="rowsps")
    b.ts("Bytes read / s (uncompressed)", (f"rate(ClickHouseProfileEvents_SelectedBytes{{{S}}}[$__rate_interval])", "{{pod}}"), unit="Bps")
    b.ts("Mark cache hit ratio",
         (f"rate(ClickHouseProfileEvents_MarkCacheHits{{{S}}}[$__rate_interval]) / (rate(ClickHouseProfileEvents_MarkCacheHits{{{S}}}[$__rate_interval])"
          f" + rate(ClickHouseProfileEvents_MarkCacheMisses{{{S}}}[$__rate_interval]))", "{{pod}}"),
         unit="percentunit", defaults={"min": 0, "max": 1})

    b.row("Merges and parts")
    b.ts("Merges running", (f"ClickHouseMetrics_Merge{{{S}}}", "merges {{pod}}"),
         (f"ClickHouseMetrics_PartMutation{{{S}}}", "mutations {{pod}}"))
    b.ts("Merged rows / s", (f"rate(ClickHouseProfileEvents_MergedRows{{{S}}}[$__rate_interval])", "{{pod}}"), unit="rowsps")
    b.ts("Merge/mutation pool usage",
         (f"ClickHouseMetrics_BackgroundMergesAndMutationsPoolTask{{{S}}} / ClickHouseMetrics_BackgroundMergesAndMutationsPoolSize{{{S}}}", "merges {{pod}}"),
         (f"ClickHouseMetrics_BackgroundFetchesPoolTask{{{S}}} / ClickHouseMetrics_BackgroundFetchesPoolSize{{{S}}}", "fetches {{pod}}"),
         (f"ClickHouseMetrics_BackgroundSchedulePoolTask{{{S}}} / ClickHouseMetrics_BackgroundSchedulePoolSize{{{S}}}", "schedule {{pod}}"),
         unit="percentunit", defaults={"min": 0, "max": 1})
    b.ts("Parts by state",
         (f"ClickHouseMetrics_PartsActive{{{S}}}", "active {{pod}}"),
         (f"ClickHouseMetrics_PartsOutdated{{{S}}}", "outdated {{pod}}"),
         (f"ClickHouseMetrics_PartsTemporary{{{S}}}", "temporary {{pod}}"))
    b.ts("Max parts per partition", (f"ClickHouseAsyncMetrics_MaxPartCountForPartition{{{S}}}", "{{pod}}"))
    b.ts("MergeTree data (rows / bytes)",
         (f"ClickHouseAsyncMetrics_TotalBytesOfMergeTreeTables{{{S}}}", "bytes {{pod}}"),
         (f"ClickHouseAsyncMetrics_TotalRowsOfMergeTreeTables{{{S}}}", "rows {{pod}}"),
         unit="bytes", overrides=[{"matcher": {"id": "byRegexp", "options": "rows.*"},
                                   "properties": [{"id": "unit", "value": "short"}, {"id": "custom.axisPlacement", "value": "right"}]}])

    b.row("Replication")
    b.ts("Replica delay", (f"ClickHouseAsyncMetrics_ReplicasMaxAbsoluteDelay{{{S}}}", "absolute {{pod}}"),
         (f"ClickHouseAsyncMetrics_ReplicasMaxRelativeDelay{{{S}}}", "relative {{pod}}"), unit="s")
    b.ts("Replication queue",
         (f"ClickHouseAsyncMetrics_ReplicasSumQueueSize{{{S}}}", "total {{pod}}"),
         (f"ClickHouseAsyncMetrics_ReplicasSumInsertsInQueue{{{S}}}", "fetches {{pod}}"),
         (f"ClickHouseAsyncMetrics_ReplicasSumMergesInQueue{{{S}}}", "merges {{pod}}"))
    b.ts("Part fetches / s",
         (f"rate(ClickHouseProfileEvents_ReplicatedPartFetches{{{S}}}[$__rate_interval])", "ok {{pod}}"),
         (f"rate(ClickHouseProfileEvents_ReplicatedPartFailedFetches{{{S}}}[$__rate_interval])", "failed {{pod}}"),
         (f"increase(ClickHouseProfileEvents_ReplicatedDataLoss{{{S}}}[$__rate_interval])", "data loss {{pod}}"))

    b.row("Keeper client (ClickHouse → Keeper)")
    b.ts("Keeper sessions / requests in flight",
         (f"ClickHouseMetrics_ZooKeeperSession{{{S}}}", "sessions {{pod}}"),
         (f"ClickHouseMetrics_ZooKeeperRequest{{{S}}}", "requests {{pod}}"),
         (f"ClickHouseMetrics_ZooKeeperWatch{{{S}}}", "watches {{pod}}"))
    b.ts("Keeper transactions / s",
         (f"rate(ClickHouseProfileEvents_ZooKeeperTransactions{{{S}}}[$__rate_interval])", "{{pod}}"), unit="reqps")
    b.ts("Keeper client errors and wait",
         (f"rate(ClickHouseProfileEvents_ZooKeeperHardwareExceptions{{{S}}}[$__rate_interval])", "hardware exc/s {{pod}}"),
         (f"rate(ClickHouseProfileEvents_ZooKeeperUserExceptions{{{S}}}[$__rate_interval])", "user exc/s {{pod}}"),
         (f"rate(ClickHouseProfileEvents_ZooKeeperWaitMicroseconds{{{S}}}[$__rate_interval]) / 1e6"
          f" / rate(ClickHouseProfileEvents_ZooKeeperTransactions{{{S}}}[$__rate_interval])", "avg wait {{pod}}"),
         overrides=[{"matcher": {"id": "byRegexp", "options": "avg wait.*"},
                     "properties": [{"id": "unit", "value": "s"}, {"id": "custom.axisPlacement", "value": "right"}]}],
         desc="Hardware exceptions = connection loss / session expiry. User exceptions include expected ones like NODEEXISTS.")

    b.row("Resources")
    b.ts("Memory",
         (f"ClickHouseAsyncMetrics_MemoryResident{{{S}}}", "resident {{pod}}"),
         (f"ClickHouseMetrics_MemoryTracking{{{S}}}", "tracked {{pod}}"),
         (f"ClickHouseAsyncMetrics_CGroupMemoryTotal{{{S}}}", "cgroup limit {{pod}}"),
         unit="bytes", overrides=[{"matcher": {"id": "byRegexp", "options": "cgroup limit.*"},
                                   "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}])
    b.ts("CPU (cores)",
         ('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="clickhouse", container="clickhouse", pod=~"$pod"}[$__rate_interval]))', "container {{pod}}"),
         (f"rate(ClickHouseProfileEvents_OSCPUVirtualTimeMicroseconds{{{S}}}[$__rate_interval]) / 1e6", "queries {{pod}}"),
         (f"ClickHouseAsyncMetrics_CGroupMaxCPU{{{S}}}", "limit {{pod}}"),
         overrides=[{"matcher": {"id": "byRegexp", "options": "limit.*"},
                     "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}])
    b.ts("Disk used (default disk)",
         (f"ClickHouseAsyncMetrics_DiskUsed_default{{{S}}} / ClickHouseAsyncMetrics_DiskTotal_default{{{S}}}", "{{pod}}"),
         unit="percentunit", defaults={"min": 0, "max": 1, "thresholds": GREEN_RED(0.8, 0.9),
                                       "custom": {"thresholdsStyle": {"mode": "line"}}})
    b.ts("Disk I/O",
         (f"rate(ClickHouseProfileEvents_ReadBufferFromFileDescriptorReadBytes{{{S}}}[$__rate_interval])", "read {{pod}}"),
         (f"rate(ClickHouseProfileEvents_WriteBufferFromFileDescriptorWriteBytes{{{S}}}[$__rate_interval])", "write {{pod}}"),
         unit="Bps")
    b.ts("Network",
         (f"rate(ClickHouseProfileEvents_NetworkReceiveBytes{{{S}}}[$__rate_interval])", "receive {{pod}}"),
         (f"rate(ClickHouseProfileEvents_NetworkSendBytes{{{S}}}[$__rate_interval])", "send {{pod}}"),
         unit="Bps")
    b.ts("Load average (1m)", (f"ClickHouseAsyncMetrics_LoadAverage1{{{S}}}", "{{pod}}"))

    b.row("Errors (system.errors)")
    codes = (f'label_replace({{__name__=~"ClickHouseErrorMetric_.+", __name__!="ClickHouseErrorMetric_ALL", {S}}},'
             f' "code", "$1", "__name__", "ClickHouseErrorMetric_(.+)")')
    err = f"increase({codes}[$__rate_interval:]) > 0"
    b.ts("Errors by code", {"expr": f"sum by (code, pod) ({err})", "legendFormat": "{{code}} {{pod}}"},
         w=14, h=9, defaults={"custom": {"drawStyle": "bars", "fillOpacity": 60, "lineWidth": 1, "stacking": {"mode": "normal"}}},
         desc="New occurrences per error code. Codes that never fire are hidden.")
    b.add("bargauge", "Errors since server start (top 15)",
          [{"expr": f"topk(15, sum by (code) ({codes}) > 0)",
            "legendFormat": "{{code}}", "instant": True}],
          w=10, h=9, defaults={"decimals": 0, "color": {"mode": "continuous-YlRd"}},
          options={"displayMode": "gradient", "orientation": "horizontal", "showUnfilled": True,
                   "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}})
    return b.dashboard("clickhouse-server", "ClickHouse server",
                       'label_values(up{job="clickhouse-http"}, pod)',
                       "ClickHouse server metrics from the built-in Prometheus endpoint (:9363).",
                       ["clickhouse", "lab"])


def keeper():
    K = 'job="keeper-metrics", pod=~"$pod"'
    b = Board()
    b.row("Ensemble")
    b.stat("Scrape up", f"up{{{K}}}", defaults={"thresholds": RED_GREEN,
           "mappings": [{"type": "value", "options": {"0": {"text": "DOWN"}, "1": {"text": "UP"}}}]})
    b.stat("Role", f"ClickHouseAsyncMetrics_KeeperIsLeader{{{K}}} * 2 + ClickHouseAsyncMetrics_KeeperIsFollower{{{K}}}"
                   f" + ClickHouseAsyncMetrics_KeeperIsObserver{{{K}}} * 3",
           w=6, defaults={"thresholds": RED_GREEN, "mappings": [{"type": "value", "options": {
               "0": {"text": "no role", "color": "red"}, "1": {"text": "follower", "color": "green"},
               "2": {"text": "leader", "color": "blue"}, "3": {"text": "observer", "color": "purple"}}}]})
    b.stat("Synced followers (leader)",
           f"max(ClickHouseAsyncMetrics_KeeperSyncedFollowers{{job=\"keeper-metrics\"}} and ClickHouseAsyncMetrics_KeeperIsLeader{{job=\"keeper-metrics\"}} == 1)",
           legend="synced", w=3, defaults={"thresholds": {"mode": "absolute", "steps": [
               {"color": "red", "value": None}, {"color": "orange", "value": 1}, {"color": "green", "value": 2}]}},
           desc="3-node ensemble: 2 synced followers means full quorum redundancy.")
    b.stat("Alive connections", f"ClickHouseMetrics_KeeperAliveConnections{{{K}}}", w=5,
           defaults={"color": {"mode": "fixed", "fixedColor": "blue"}})
    b.stat("Znodes", f"ClickHouseAsyncMetrics_KeeperZnodeCount{{{K}}}", w=6,
           defaults={"color": {"mode": "fixed", "fixedColor": "blue"}})

    b.row("Requests")
    b.ts("Requests / s", (f"rate(ClickHouseProfileEvents_KeeperRequestTotal{{{K}}}[$__rate_interval])", "{{pod}}"), unit="reqps")
    reqs = ["Create", "Remove", "Set", "Get", "List", "Exists", "Check", "Multi", "MultiRead"]
    b.ts("Requests / s by type (all nodes)",
         *[(f"sum(rate(ClickHouseProfileEvents_Keeper{r}Request{{{K}}}[$__rate_interval]))", r.lower()) for r in reqs],
         unit="reqps", defaults={"custom": {"stacking": {"mode": "normal"}, "fillOpacity": 40, "lineWidth": 1, "showPoints": "never"}})
    b.ts("Latency", (f"ClickHouseAsyncMetrics_KeeperAvgLatency{{{K}}}", "avg {{pod}}"),
         (f"ClickHouseAsyncMetrics_KeeperMaxLatency{{{K}}}", "max {{pod}}"), unit="ms",
         desc="Keeper's own 4lw 'mntr' latency counters (milliseconds, since start/reset).")
    b.ts("Outstanding requests", (f"ClickHouseMetrics_KeeperOutstandingRequests{{{K}}}", "{{pod}}"))
    b.ts("Packets / s",
         (f"rate(ClickHouseProfileEvents_KeeperPacketsReceived{{{K}}}[$__rate_interval])", "received {{pod}}"),
         (f"rate(ClickHouseProfileEvents_KeeperPacketsSent{{{K}}}[$__rate_interval])", "sent {{pod}}"), unit="pps")
    b.ts("Avg request processing time",
         (f"rate(ClickHouseProfileEvents_KeeperTotalElapsedMicroseconds{{{K}}}[$__rate_interval]) / 1e6"
          f" / rate(ClickHouseProfileEvents_KeeperRequestTotal{{{K}}}[$__rate_interval])", "{{pod}}"), unit="s")

    b.row("Raft log and snapshots")
    b.ts("Log index", (f"ClickHouseAsyncMetrics_KeeperLastLogIdx{{{K}}}", "last {{pod}}"),
         (f"ClickHouseAsyncMetrics_KeeperLastCommittedLogIdx{{{K}}}", "committed {{pod}}"),
         (f"ClickHouseAsyncMetrics_KeeperLastSnapshotIdx{{{K}}}", "snapshot {{pod}}"))
    b.ts("Uncommitted entries (last - committed)",
         (f"ClickHouseAsyncMetrics_KeeperLastLogIdx{{{K}}} - ClickHouseAsyncMetrics_KeeperLastCommittedLogIdx{{{K}}}", "{{pod}}"),
         desc="A follower that stays behind is lagging or partitioned from the leader.")
    b.ts("Commits / snapshots",
         (f"rate(ClickHouseProfileEvents_KeeperCommits{{{K}}}[$__rate_interval])", "commits/s {{pod}}"),
         (f"rate(ClickHouseProfileEvents_KeeperCommitsFailed{{{K}}}[$__rate_interval])", "failed commits/s {{pod}}"),
         (f"increase(ClickHouseProfileEvents_KeeperSnapshotCreations{{{K}}}[$__rate_interval])", "snapshots {{pod}}"),
         (f"increase(ClickHouseProfileEvents_KeeperSnapshotCreationsFailed{{{K}}}[$__rate_interval])", "failed snapshots {{pod}}"))

    b.row("State")
    b.ts("Znodes", (f"ClickHouseAsyncMetrics_KeeperZnodeCount{{{K}}}", "{{pod}}"))
    b.ts("Watches and ephemerals",
         (f"ClickHouseAsyncMetrics_KeeperWatchCount{{{K}}}", "watches {{pod}}"),
         (f"ClickHouseAsyncMetrics_KeeperEphemeralsCount{{{K}}}", "ephemerals {{pod}}"))
    b.ts("Approximate data size", (f"ClickHouseAsyncMetrics_KeeperApproximateDataSize{{{K}}}", "{{pod}}"), unit="bytes")

    b.row("Resources")
    b.ts("Memory",
         (f"ClickHouseAsyncMetrics_MemoryResident{{{K}}}", "resident {{pod}}"),
         (f"ClickHouseAsyncMetrics_CGroupMemoryTotal{{{K}}}", "cgroup limit {{pod}}"), unit="bytes",
         overrides=[{"matcher": {"id": "byRegexp", "options": "cgroup limit.*"},
                     "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}])
    b.ts("CPU (cores)",
         ('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="clickhouse", container="clickhouse-keeper", pod=~"$pod"}[$__rate_interval]))', "{{pod}}"))
    b.ts("File descriptors / rejected connections",
         (f"ClickHouseAsyncMetrics_KeeperOpenFileDescriptorCount{{{K}}}", "open fds {{pod}}"),
         (f"ClickHouseAsyncMetrics_KeeperTCPRejectedConnections{{{K}}}", "rejected conns {{pod}}"))
    return b.dashboard("clickhouse-keeper", "ClickHouse Keeper",
                       'label_values(up{job="keeper-metrics"}, pod)',
                       "ClickHouse Keeper ensemble metrics from each Keeper's Prometheus endpoint (:7000).",
                       ["clickhouse", "keeper", "lab"])


for name, fn in [("clickhouse-server.json", server), ("clickhouse-keeper.json", keeper)]:
    with open(OUT / name, "w") as f:
        json.dump(fn(), f, indent=2)
        f.write("\n")
