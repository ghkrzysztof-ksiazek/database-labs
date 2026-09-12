# MySQL backup, restore and PITR test suite — design

Date: 2026-09-11
Lab directory: `20260911-mysql-replication-backups/`
Status: approved for implementation

## Purpose

Turn the copied MySQL replication lab into a lab whose subject is **backup
verification**: produce backups, restore them, recover to a point in time, and —
the part that actually proves anything — restore into a separate cluster, attach
it as a replica of the live cluster, and let it catch up.

The output is two things at once: a runnable Ansible-driven test suite, and
documentation carrying real measured output that can be turned into a blog post.

The thesis the documentation must land: **a green backup job proves nothing. A
backup is verified only when it has been restored and the restored copy has been
shown to be a consistent, usable database.** Scenario 12 is that proof; the other
eleven are the supporting cast.

## Constraints

- Infrastructure stays as it is today: kind cluster `mysql-lab`, Percona Operator
  for MySQL 1.2.0, Percona Server 8.4 with one source and one replica, HAProxy,
  Orchestrator, in-cluster MinIO, kube-prometheus-stack. The only infrastructure
  change is enabling PITR, which is currently absent.
- Ansible remains the driver; `make` targets remain the interface.
- Everything runs on one laptop Docker host with about 8 GB of RAM.
- Lab-grade credentials stay as they are and stay clearly labelled as such.

## Verified facts about operator 1.2.0

Checked against the running CRDs and upstream `v1.2.0` manifests before writing
this spec:

- `PerconaServerMySQL.spec.backup.pitr` exists: `{enabled, binlogServer}`. The
  binlog server streams binary logs to S3-compatible storage and takes
  `storage.s3 {bucket, credentialsSecret, endpointUrl, prefix, region}`, plus
  `checkpointInterval`, `checkpointSize`, `serverId`, timeouts and `logLevel`.
- Binlog server image: `percona/percona-server-mysql-operator:1.2.0-binlog-server-0.4.1`
  (the plain `1.2.0` tag is the operator, not the binlog server; `0.4.1` is the
  newest binlog-server build published for 1.2.0).
- `PerconaServerMySQLRestore.spec.pitr` = `{type: date|gtid, date, gtid, force,
  backupSource.binlogServer}`. Live correction: this pinned binlog-server build requires UTC without a suffix, e.g. `"2024-11-18T11:10:48"`; the sample RFC3339 `Z` suffix is rejected.
- `PerconaServerMySQLBackup.spec` = `{clusterName, storageName, type: full|incremental,
  incrementalBaseBackupName, sourcePod, containerOptions}`.
- `PerconaServerMySQLRestore.spec.backupSource` = `{destination, compressed, storage}`,
  which allows restoring from a MinIO path without the original backup object —
  the mechanism scenario 12 uses to restore into a different cluster.
- Backup status carries `state`, `stateDescription`, `destination`, `completed`,
  `type`, `compressed`.

## Scope

### Removed (content, not infrastructure)

Deleted outright:

- `ansible/playbooks/failover.yml` and `ansible/roles/failover_test/`
- `ansible/playbooks/scale-out.yml` and `ansible/roles/scale_out/`
- the corresponding `make` and `scripts/lab.sh` targets
- `tests/__pycache__/`
- `docs/cluster-and-data.md` (its backup-relevant content is folded into the new
  architecture document)

Rewritten from scratch for the backup subject:

- `README.md` — currently describes the replication lab and points readers at the
  wrong directory
- `docs/how-it-works.md` → replaced by `docs/backup-architecture.md`
- `docs/blog-draft.md` — currently yesterday's failover post
- `docs/diagrams/architecture.mmd`

Orchestrator, HAProxy, the replica, MinIO and the monitoring stack all stay.

### Added — PITR

- `ansible/inventory/group_vars/all.yml`: `pitr_enabled: true`,
  `binlog_server_image`, `binlog_bucket: mysql-lab-binlogs`,
  `binlog_prefix`, `binlog_checkpoint_interval`, `binlog_server_resources`.
- `ansible/roles/mysql_cluster/templates/cluster.yaml.j2`: a `backup.pitr` block,
  rendered only when `pitr_enabled`, with `binlogServer.storage.s3` pointing at
  the MinIO binlog bucket and modest resource requests.
- `ansible/roles/minio/tasks/main.yml`: create the binlog bucket alongside the
  backup bucket. A separate bucket, not a prefix, so that binlog streaming is
  visible on its own in a `mc ls`.

## Test suite architecture

### Layout

```
ansible/playbooks/tests/t01-backup-full.yml … t12-restore-as-replica.yml
ansible/playbooks/tests/all.yml          # ordered run + report
ansible/roles/test_common/              # shared: result recording, cluster health gate
ansible/roles/t01_backup_full/ … t12_restore_as_replica/
```

Each scenario is one role plus one thin playbook, so any scenario can be run
alone (`make test-t09`) or as part of the ordered suite (`make test-backups`).

### Result recording

`test_common` provides:

- `record_result.yml` — appends one JSON object per scenario to
  `{{ repo_root }}/docs/results/<run_id>.jsonl`:
  `{scenario, title, status, started, finished, duration_seconds, evidence[]}`.
  `evidence` holds the literal command output lines that justify the verdict, so
  the documentation quotes measured text rather than prose.
- `health_gate.yml` — asserts the cluster is healthy before and after a scenario:
  expected pod count Running, primary writable, replica IO and SQL threads on.
  A scenario that leaves the lab broken fails loudly instead of poisoning the
  next one.

A `report` role renders the JSONL into `docs/results/<run_id>-run.md`: a summary
table, then per-scenario detail with durations and evidence blocks.

Failure policy: a scenario that fails records `status: failed` with its evidence,
and the ordered run stops at that point rather than continuing on a damaged
cluster. A failed run renders its partial report; there is no supported continue-on-error switch.

### Scenarios

Ordering is load-bearing — every restore needs a good backup behind it, and the
destructive scenarios must not strand the lab.

| # | Scenario | Method | Assertions |
|---|---|---|---|
| 01 | On-demand full backup | `PerconaServerMySQLBackup` type `full` | reaches Succeeded; `status.destination` is the MinIO bucket; duration recorded |
| 02 | Backup from a replica | same, with `sourcePod: lab-mysql-1` | succeeds; the backup pod ran against the replica; the primary served writes throughout |
| 03 | Incremental on a full base | `type: incremental`, `incrementalBaseBackupName` = 01 | succeeds; its MinIO object is materially smaller than the full |
| 04 | Storage contents | `mc ls --recursive` job against MinIO | backup prefix holds nonzero XtraBackup chunks and MD5 metadata; controlled writes increase archived binlog bytes |
| 05 | Scheduled backup | patch `backup.schedule` to a short interval | a `cron-*` backup object appears and reaches Succeeded without human action |
| 06 | Retention (`keep`) | let N+1 scheduled runs complete with `keep: N` | oldest successful backup CR and data prefix are gone; residual MD5 sidecars are reported separately |
| 07 | Restore in place | canary table created after the backup; restore 01 | restore Succeeded; canary absent; 10 sysbench tables and the expected data size return |
| 08 | Disaster: dropped table | `DROP TABLE sbtest10`; restore | table returns with its full row count |
| 09 | **PITR to a timestamp** | marker rows at t1, pause, marker rows at t2; restore with `pitr.type: date` targeting between them | restore Succeeded; t1 markers present, t2 markers absent |
| 10 | **PITR to a GTID** | capture `@@GLOBAL.gtid_executed` before a destructive statement; restore with `pitr.type: gtid` | restore Succeeded; the destructive statement's effect is absent, everything before it present |
| 11 | Negative: impossible PITR target | restore targeting a timestamp before the backup exists | the restore fails and says why; the cluster is still healthy afterwards |
| 12 | **Restore into a new cluster and replicate** | see below | see below |

Scenarios 01–06 prove backups are produced. 07–11 prove they restore in place.
Only 12 proves the backup is a usable database.

### Scenario 12 in detail

Steps:

1. Reference the full backup from scenario 01 by its MinIO destination, via
   `restore.spec.backupSource.destination` + `storage`, so the new cluster does
   not depend on the source cluster's backup object.
2. Copy `lab-secrets` and the operator-generated `internal-lab` secret to
   `verify-secrets` and `internal-verify`. This is the step that is easy to miss
   and must be called out in the documentation: the restored datadir carries
   `lab`'s `mysql.user` table, so the new cluster has to be handed the same
   credentials or the operator cannot authenticate against the data it has just
   restored. The SSL secret is copied too if the operator requires it.
3. Create a second `PerconaServerMySQL` named `verify` in the same namespace:
   `mysql.size: 1`, Orchestrator disabled, HAProxy disabled, PITR disabled, same
   MinIO storage definition, smaller resource requests.
4. Apply `PerconaServerMySQLRestore` with `clusterName: verify` and that
   `backupSource`.
5. Keep writing to `lab` during the restore, so the backup is provably stale by
   the time it lands and the replica has real work to catch up on.
6. On the restored node, `CHANGE REPLICATION SOURCE TO … SOURCE_AUTO_POSITION = 1`
   pointed at `lab`'s primary service, using the replication credentials from the
   copied secret. XtraBackup restores `gtid_purged`, so auto-position resumes
   exactly where the backup ended and no binary-log coordinates are copied by hand.
7. Start the replica and wait for it to catch up.

Assertions:

- `Replica_IO_Running` and `Replica_SQL_Running` are both `Yes`
- `Seconds_Behind_Source` reaches 0 within the timeout
- `verify`'s `Executed_Gtid_Set` is a superset of the backup's `gtid_purged`
- the rows written during step 5 — invisible to the backup — are present on `verify`
- with writes stopped, `CHECKSUM TABLE` for all 10 sysbench tables matches `lab`

Recorded for the documentation: restore duration, catch-up duration, the size of
the GTID gap replayed, and the row delta that existed at attach time.

Teardown: the `verify` cluster and its copied secrets are deleted at the end, so
the suite leaves the lab as it found it.

Risk, stated plainly: cross-cluster restore plus secret copying is the
least-travelled path in the operator. If it needs iteration or cannot be made to
work as described, the documentation records what happened and why rather than
quietly dropping the scenario.

## Interfaces

New `make` targets, mirrored in `scripts/lab.sh`:

```
make backup            # existing on-demand backup (kept)
make restore           # existing in-place restore (kept)
make test-backups      # ordered scenarios 01-12 + report
make test-t01 … t12    # a single scenario
make report            # re-render the last run's markdown
```

## Documentation

- `README.md` — what the lab is, prerequisites, quick start, the twelve
  scenarios, service endpoints, defaults. Correct directory name throughout.
- `docs/backup-architecture.md` — how the pieces fit: XtraBackup jobs, the binlog
  server streaming to MinIO, the operator's backup and restore CRs, PITR
  mechanics with GTIDs, and how a restore into a fresh cluster becomes a replica.
  Mermaid diagrams for the backup path, the PITR restore path, and the
  restore-as-replica path.
- `docs/test-catalogue.md` — per scenario: what it proves, how it does it, what
  it asserts, roughly how long it takes, and how to run it alone.
- `docs/results/<run_id>-run.md` — generated, measured, unedited.
- `docs/blog-draft.md` — the publishable narrative, built on the measured run,
  with scenario 12 as the argument and the rest as evidence.
- `tests/test_lab_config.py` — structural tests updated: the PITR block renders
  when enabled and is absent when not, the binlog bucket is created, every
  scenario role has a playbook and a `make` target, no references remain to the
  removed failover and scale-out paths.

`tests/test_lab_config.py` is offline and fast; it is not the backup test suite,
it guards the shipped templates.

## Execution plan

1. Tear down the existing broken `mysql-lab` cluster.
2. Implement the PITR change, the suite, and the structural tests.
3. `make deploy`, `make load-data`.
4. Run the full suite; iterate on whatever breaks.
5. Write the documentation against the recorded results; no number appears in the
   documentation that did not come out of a run.

Expected wall clock for a full pass: roughly 1.5–2 hours, dominated by restores.

## Out of scope

Encryption at rest, cloud object stores, cross-region DR, incremental restore
chains beyond scenario 03, and backup performance tuning. The lab is a
correctness demonstration on a laptop, not a benchmark.

## Live-run refinements

The implementation plan continuation notes and lab documentation record the measured corrections: unique per-attempt PITR markers, a new archive prefix for each recovery history, GTID differences excluding inherited history, full S3 storage metadata for cross-cluster restore, and GTID/checksum verification followed by cleanup before PASS. These refine the original design without changing the infrastructure scope.
