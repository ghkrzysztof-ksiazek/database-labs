# MySQL Backup, Restore and PITR Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `20260911-mysql-replication-backups/` into a lab whose subject is backup verification — twelve Ansible-driven scenarios covering backup creation, storage, retention, in-place restore, point-in-time recovery, and a restore into a separate cluster that attaches as a replica and catches up — with generated, measured result reports and blog-ready documentation.

**Architecture:** The existing kind + Percona Operator for MySQL 1.2.0 lab is left intact; PITR (binlog server streaming to MinIO) is the only infrastructure addition. Each scenario is one Ansible role plus one thin playbook under `ansible/playbooks/tests/`, individually runnable and composable into an ordered suite. Scenario roles follow the existing lab idiom: a `ansible.builtin.shell` block driving `kubectl`/`mysql` that echoes `KEY=value` evidence lines, followed by `assert` tasks parsing those lines. A shared `test_common` role records each result to JSONL and gates cluster health; a `report` role renders the JSONL to markdown.

**Tech Stack:** Ansible (`kubernetes.core`), kind, Kubernetes, Percona Operator for MySQL 1.2.0, Percona Server 8.4, Percona XtraBackup 8.4, Percona binlog server `1.2.0-binlog-server-0.4.1`, MinIO, Python `unittest` + Jinja2 for offline structural tests.

**Spec:** `docs/superpowers/specs/2026-09-11-mysql-backup-pitr-test-suite-design.md`

## Global Constraints

- All paths below are relative to `20260911-mysql-replication-backups/` unless stated otherwise. That directory is the working directory for every command.
- Infrastructure stays as it is: kind cluster `mysql-lab`, namespace `mysql`, cluster name `lab`, `mysql_size: 2` (one source + one replica), HAProxy, Orchestrator, MinIO, kube-prometheus-stack. The only infrastructure change in this plan is enabling PITR.
- Binlog server image is exactly `percona/percona-server-mysql-operator:1.2.0-binlog-server-0.4.1`. The plain `1.2.0` tag is the operator, not the binlog server.
- Restore PITR `date` values are RFC3339 UTC with a `Z` suffix, e.g. `2026-09-11T20:14:05Z`. Capture them with `SELECT UTC_TIMESTAMP()` on the server and reformat, never from the laptop clock.
- Restore PITR `type` is one of `date` or `gtid` — no other value validates.
- Backup CR names must be DNS-1123 labels: lowercase alphanumerics and `-`.
- Results are written to `docs/results/<run_id>.jsonl` and `docs/results/<run_id>-run.md`, where `run_id` is a UTC stamp like `20260911T201405Z`.
- No number appears in any document that did not come out of a real run. Placeholders are not acceptable in the final documentation.
- Lab-grade credentials (`root`/`mysql`, `admin`/`admin`, `minio`/`minio12345`) stay as they are and stay labelled as lab-only.
- Every task ends with a commit. Offline structural tests (`make test`) must pass before each commit.

---

### Task 1: Prune the replication-lab content

Remove what belongs to yesterday's failover post, so the lab has one subject. Infrastructure is untouched — only the two operation playbooks that are about failover and scale-out, plus their entrypoints and the stale structural tests that pin them.

**Files:**
- Delete: `ansible/playbooks/failover.yml`, `ansible/playbooks/scale-out.yml`
- Delete: `ansible/roles/failover_test/` (whole directory), `ansible/roles/scale_out/` (whole directory)
- Delete: `docs/cluster-and-data.md`, `tests/__pycache__/`
- Modify: `Makefile`, `scripts/lab.sh`, `ansible/inventory/group_vars/all.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a `Makefile` and `scripts/lab.sh` whose target list is `bootstrap test deploy load-data verify backup restore teardown`; later tasks add test targets to both.

- [ ] **Step 1: Rewrite the two stale structural tests to assert the pruning**

In `tests/test_lab_config.py`, replace `test_ops_playbooks_exist_and_target_live_cluster`, `test_lab_entrypoints_and_repo_index`, `test_failover_role_requires_replica_rejoin_after_force_delete` and `test_docs_describe_force_delete_failover_not_sigstop` with:

```python
    def test_ops_playbooks_exist_and_target_live_cluster(self) -> None:
        for name in (
            "site.yml",
            "load-data.yml",
            "verify.yml",
            "teardown.yml",
            "backup.yml",
            "restore.yml",
        ):
            path = PLAYBOOKS / name
            self.assertTrue(path.is_file(), f"missing playbook {name}")
            text = path.read_text()
            self.assertIn("kubeconfig", text)
            self.assertNotIn("unittest.mock", text)

        verify = (PLAYBOOKS / "verify.yml").read_text()
        self.assertIn("sysbench", verify.lower() + verify)
        self.assertIn("10", verify)
        self.assertIn("Prometheus", verify + verify.lower())

    def test_failover_and_scale_out_are_gone(self) -> None:
        for gone in (
            PLAYBOOKS / "failover.yml",
            PLAYBOOKS / "scale-out.yml",
            ANSIBLE / "roles" / "failover_test",
            ANSIBLE / "roles" / "scale_out",
            ROOT / "docs" / "cluster-and-data.md",
        ):
            self.assertFalse(gone.exists(), f"{gone} should have been removed")

        makefile = (ROOT / "Makefile").read_text()
        lab_sh = (ROOT / "scripts" / "lab.sh").read_text()
        for word in ("failover", "scale-out", "scale_out"):
            self.assertNotIn(word, makefile)
            self.assertNotIn(word, lab_sh)

    def test_lab_entrypoints_and_repo_index(self) -> None:
        makefile = (ROOT / "Makefile").read_text()
        for target in ("deploy", "load-data", "verify", "backup", "restore", "teardown"):
            self.assertIn(target, makefile)
        index = REPO_README.read_text()
        self.assertIn("20260911-mysql-replication-backups", index)
```

Also drop `self.assertGreater(int(v["mysql_scale_out_size"]), int(v["mysql_size"]))` from `test_group_vars_define_async_source_replica_topology`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `test_failover_and_scale_out_are_gone` reports the playbooks and roles still exist, and `test_lab_entrypoints_and_repo_index` reports the repo README does not mention this directory.

- [ ] **Step 3: Delete the failover and scale-out material**

```bash
rm -f ansible/playbooks/failover.yml ansible/playbooks/scale-out.yml
rm -rf ansible/roles/failover_test ansible/roles/scale_out
rm -f docs/cluster-and-data.md
rm -rf tests/__pycache__
```

Remove `mysql_scale_out_size: 3` from `ansible/inventory/group_vars/all.yml`.

- [ ] **Step 4: Remove the entrypoint targets**

In `Makefile`, delete the `failover:` and `scale-out:` targets and drop both words from the `.PHONY` line. In `scripts/lab.sh`, delete the `failover)` and `scale-out)` cases and remove both from the usage string.

- [ ] **Step 5: Point the repo index at this lab**

In the repository root `README.md` (one directory up), add a line for `20260911-mysql-replication-backups` describing it as the MySQL backup, restore and PITR verification lab, alongside the existing entries.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test`
Expected: PASS, all tests.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Prune failover and scale-out material from the backup lab"
```

---

### Task 2: Enable PITR in the installer

Add the binlog server to the cluster CR and a dedicated MinIO bucket for binlogs. A separate bucket, not a prefix, so binlog streaming is visible on its own in a listing.

**Files:**
- Modify: `ansible/inventory/group_vars/all.yml`
- Modify: `ansible/roles/mysql_cluster/templates/cluster.yaml.j2`
- Modify: `ansible/roles/minio/tasks/main.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: existing `backup_bucket`, `minio_credentials_secret`, `mysql_namespace` vars.
- Produces: vars `pitr_enabled` (bool), `binlog_bucket` (str, `mysql-lab-binlogs`), `binlog_prefix` (str, `lab`), `binlog_server_image`, `binlog_checkpoint_interval`, `binlog_server_id`. Scenario roles in Tasks 7 and 8 consume `binlog_bucket`, `binlog_prefix`, `binlog_server_image` and `binlog_server_id`.

- [ ] **Step 1: Write the failing structural test**

Add to `tests/test_lab_config.py`:

```python
    def test_cluster_template_enables_pitr_binlog_server(self) -> None:
        v = load_group_vars()
        self.assertTrue(v["pitr_enabled"])
        self.assertEqual(v["binlog_bucket"], "mysql-lab-binlogs")
        self.assertNotEqual(v["binlog_bucket"], v["backup_bucket"])
        self.assertIn("binlog-server", v["binlog_server_image"])

        rendered = yaml.safe_load(render_template(TEMPLATES_CLUSTER / "cluster.yaml.j2"))
        pitr = rendered["spec"]["backup"]["pitr"]
        self.assertTrue(pitr["enabled"])
        s3 = pitr["binlogServer"]["storage"]["s3"]
        self.assertEqual(s3["bucket"], v["binlog_bucket"])
        self.assertEqual(s3["credentialsSecret"], v["minio_credentials_secret"])
        self.assertIn("minio", s3["endpointUrl"])
        self.assertEqual(pitr["binlogServer"]["image"], v["binlog_server_image"])

    def test_cluster_template_omits_pitr_when_disabled(self) -> None:
        rendered = yaml.safe_load(
            render_template(TEMPLATES_CLUSTER / "cluster.yaml.j2", {"pitr_enabled": False})
        )
        self.assertNotIn("pitr", rendered["spec"]["backup"])

    def test_minio_role_creates_both_buckets(self) -> None:
        text = (ANSIBLE / "roles" / "minio" / "tasks" / "main.yml").read_text()
        self.assertIn("binlog_bucket", text)
        self.assertIn("backup_bucket", text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL with `KeyError: 'pitr_enabled'`.

- [ ] **Step 3: Add the variables**

Append to `ansible/inventory/group_vars/all.yml`, after the existing backup block:

```yaml
pitr_enabled: true
binlog_bucket: mysql-lab-binlogs
binlog_prefix: lab
binlog_server_image: "percona/percona-server-mysql-operator:1.2.0-binlog-server-0.4.1"
binlog_checkpoint_interval: 30s
binlog_checkpoint_size: 16M
binlog_server_id: 1001
```

- [ ] **Step 4: Render the PITR block in the cluster template**

In `ansible/roles/mysql_cluster/templates/cluster.yaml.j2`, inside `spec.backup`, directly after the `enabled: true` line, insert:

```jinja
{% if pitr_enabled %}
    pitr:
      enabled: true
      binlogServer:
        size: 1
        image: {{ binlog_server_image }}
        imagePullPolicy: IfNotPresent
        serverId: {{ binlog_server_id }}
        checkpointInterval: {{ binlog_checkpoint_interval }}
        checkpointSize: {{ binlog_checkpoint_size }}
        logLevel: info
        storage:
          s3:
            bucket: {{ binlog_bucket }}
            credentialsSecret: {{ minio_credentials_secret }}
            endpointUrl: http://minio.{{ mysql_namespace }}.svc.cluster.local:9000
            region: us-east-1
            prefix: {{ binlog_prefix }}
        resources:
          requests:
            cpu: 50m
            memory: 128Mi
          limits:
            memory: 256Mi
{% endif %}
```

- [ ] **Step 5: Create the binlog bucket**

In `ansible/roles/minio/tasks/main.yml`, in the `Create backup bucket` job's shell command, replace the `mc mb`/`mc ls` lines with:

```yaml
                    mc alias set local http://minio:9000 "{{ minio_root_user }}" "{{ minio_root_password }}"
                    mc mb --ignore-existing local/{{ backup_bucket }}
                    mc mb --ignore-existing local/{{ binlog_bucket }}
                    mc ls local/
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Enable PITR binlog server streaming to a dedicated MinIO bucket"
```

---

### Task 3: Test harness foundation

The shared machinery every scenario uses: result recording, a cluster health gate, the ordered runner, the markdown report, and the `make` targets.

**Files:**
- Create: `ansible/roles/test_common/defaults/main.yml`
- Create: `ansible/roles/test_common/tasks/health_gate.yml`
- Create: `ansible/roles/test_common/tasks/record_result.yml`
- Create: `ansible/roles/test_report/tasks/main.yml`
- Create: `ansible/roles/test_report/templates/run.md.j2`
- Create: `ansible/playbooks/tests/all.yml`
- Create: `ansible/playbooks/tests/report.yml`
- Create: `docs/results/.gitkeep`
- Modify: `Makefile`, `scripts/lab.sh`, `.gitignore`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: `kubeconfig_path`, `mysql_namespace`, `mysql_cluster_name`, `mysql_root_password`, `mysql_size` from group_vars.
- Produces, for every later task:
  - `run_id` — extra-var, a UTC stamp; defaults to `manual` when a scenario runs alone.
  - `test_common/tasks/health_gate.yml` — include with no arguments; asserts the lab is healthy and sets fact `health_summary` (string).
  - `test_common/tasks/record_result.yml` — include with `vars:` `scenario_id` (str, e.g. `t01`), `scenario_title` (str), `scenario_status` (str, `passed` or `failed`), `scenario_started` (int, epoch seconds), `scenario_evidence` (list of str). Appends one JSON line to `docs/results/{{ run_id }}.jsonl`.
  - Convention every scenario role follows: `set_fact t_start` at the top, one shell block registered as `out`, asserts, then `record_result.yml` with `scenario_evidence: "{{ out.stdout_lines }}"`.

- [ ] **Step 1: Write the failing structural test**

Add to `tests/test_lab_config.py`:

```python
    SCENARIOS = (
        ("t01", "backup-full"),
        ("t02", "backup-from-replica"),
        ("t03", "backup-incremental"),
        ("t04", "storage-contents"),
        ("t05", "backup-scheduled"),
        ("t06", "backup-retention"),
        ("t07", "restore-in-place"),
        ("t08", "restore-dropped-table"),
        ("t09", "pitr-timestamp"),
        ("t10", "pitr-gtid"),
        ("t11", "pitr-invalid-target"),
        ("t12", "restore-as-replica"),
    )

    def test_test_harness_is_wired(self) -> None:
        common = ANSIBLE / "roles" / "test_common" / "tasks"
        self.assertTrue((common / "health_gate.yml").is_file())
        self.assertTrue((common / "record_result.yml").is_file())
        record = (common / "record_result.yml").read_text()
        self.assertIn("scenario_id", record)
        self.assertIn("scenario_status", record)
        self.assertIn("scenario_evidence", record)
        self.assertIn(".jsonl", record)

        all_yml = (PLAYBOOKS / "tests" / "all.yml").read_text()
        makefile = (ROOT / "Makefile").read_text()
        lab_sh = (ROOT / "scripts" / "lab.sh").read_text()
        self.assertIn("test-backups", makefile)
        self.assertIn("test-backups", lab_sh)
        for sid, _ in self.SCENARIOS:
            self.assertIn(sid, all_yml, f"{sid} missing from the ordered run")
            self.assertIn(f"test-{sid}", makefile, f"make test-{sid} missing")
```

(The per-scenario playbook and role assertions arrive in Task 4; this step only proves the harness and the ordering exist.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `ansible/roles/test_common/tasks/health_gate.yml` does not exist.

- [ ] **Step 3: Write the test_common defaults**

`ansible/roles/test_common/defaults/main.yml`:

```yaml
---
run_id: manual
results_dir: "{{ repo_root }}/docs/results"
results_file: "{{ results_dir }}/{{ run_id }}.jsonl"
health_timeout_retries: 60
health_timeout_delay: 10
```

- [ ] **Step 4: Write the health gate**

`ansible/roles/test_common/tasks/health_gate.yml`:

```yaml
---
# Asserts the lab is usable. Included before and after every scenario so a
# scenario that damages the cluster fails loudly instead of poisoning the next.
- name: Wait for MySQL pods to be Running
  kubernetes.core.k8s_info:
    kubeconfig: "{{ kubeconfig_path }}"
    kind: Pod
    namespace: "{{ mysql_namespace }}"
    label_selectors:
      - app.kubernetes.io/instance={{ mysql_cluster_name }}
      - app.kubernetes.io/component=database
  register: health_pods
  until:
    - health_pods.resources | length >= (mysql_size | int)
    - health_pods.resources | rejectattr('status.phase', 'equalto', 'Running') | list | length == 0
  retries: "{{ health_timeout_retries }}"
  delay: "{{ health_timeout_delay }}"

- name: Collect primary and replica state
  ansible.builtin.shell: |
    set -euo pipefail
    export KUBECONFIG="{{ kubeconfig_path }}"
    NS="{{ mysql_namespace }}"
    pods=$(kubectl -n "$NS" get pods -l app.kubernetes.io/instance={{ mysql_cluster_name }},app.kubernetes.io/component=database \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort)
    primary=""
    replica_ok=0
    for p in $pods; do
      ro=$(kubectl -n "$NS" exec "$p" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "SELECT @@read_only" 2>/dev/null | tr -d '\r')
      if [ "$ro" = "0" ]; then
        primary="$p"
      else
        io=$(kubectl -n "$NS" exec "$p" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT SERVICE_STATE FROM performance_schema.replication_connection_status LIMIT 1" 2>/dev/null | tr -d '\r')
        sql=$(kubectl -n "$NS" exec "$p" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT SERVICE_STATE FROM performance_schema.replication_applier_status LIMIT 1" 2>/dev/null | tr -d '\r')
        if [ "$io" = "ON" ] && [ "$sql" = "ON" ]; then
          replica_ok=$((replica_ok+1))
        fi
      fi
    done
    echo "PRIMARY=$primary"
    echo "REPLICA_OK=$replica_ok"
    bs=$(kubectl -n "$NS" get pods -l app.kubernetes.io/component=binlog-server \
      -o jsonpath='{range .items[*]}{.metadata.name}={.status.phase}{"\n"}{end}' 2>/dev/null | tr '\n' ' ')
    echo "BINLOG_SERVER=${bs:-none}"
  args:
    executable: /bin/bash
  register: health_out
  changed_when: false
  retries: 10
  delay: 15
  until: health_out.rc == 0

- name: Require a writable primary and healthy replicas
  ansible.builtin.assert:
    that:
      - health_out.stdout is search('PRIMARY=' ~ mysql_cluster_name)
      - (health_out.stdout_lines | select('match', '^REPLICA_OK=') | first).split('=')[1] | int
        >= ((mysql_size | int) - 1)
    fail_msg: "Cluster is not healthy: {{ health_out.stdout }}"

- name: Publish the health summary
  ansible.builtin.set_fact:
    health_summary: "{{ health_out.stdout_lines | join(' | ') }}"
```

- [ ] **Step 5: Write the result recorder**

`ansible/roles/test_common/tasks/record_result.yml`:

```yaml
---
# Appends one JSON object per scenario to docs/results/<run_id>.jsonl.
# Callers pass: scenario_id, scenario_title, scenario_status,
# scenario_started (epoch seconds), scenario_evidence (list of strings).
- name: Ensure the results directory exists
  ansible.builtin.file:
    path: "{{ results_dir }}"
    state: directory
    mode: "0755"

- name: Append the scenario result
  ansible.builtin.lineinfile:
    path: "{{ results_file }}"
    create: true
    mode: "0644"
    insertafter: EOF
    line: >-
      {{
        {
          'scenario': scenario_id,
          'title': scenario_title,
          'status': scenario_status,
          'started': scenario_started | int,
          'finished': (lookup('pipe', 'date -u +%s') | int),
          'duration_seconds': ((lookup('pipe', 'date -u +%s') | int) - (scenario_started | int)),
          'evidence': scenario_evidence | default([]),
        } | to_json
      }}

- name: Show the scenario verdict
  ansible.builtin.debug:
    msg: "{{ scenario_id }} {{ scenario_status | upper }} — {{ scenario_title }}"
```

- [ ] **Step 6: Write the report role**

`ansible/roles/test_report/tasks/main.yml`:

```yaml
---
- name: Read the run results
  ansible.builtin.slurp:
    src: "{{ results_file }}"
  register: results_raw

- name: Parse the run results
  ansible.builtin.set_fact:
    results: >-
      {{ (results_raw.content | b64decode).splitlines()
         | select('match', '^\\s*\\{')
         | map('from_json') | list }}

- name: Render the run report
  ansible.builtin.template:
    src: run.md.j2
    dest: "{{ results_dir }}/{{ run_id }}-run.md"
    mode: "0644"

- name: Show where the report landed
  ansible.builtin.debug:
    msg: >-
      {{ results | selectattr('status', 'equalto', 'passed') | list | length }}/{{ results | length }}
      scenarios passed — {{ results_dir }}/{{ run_id }}-run.md
```

`ansible/roles/test_report/templates/run.md.j2`:

```jinja
# Backup, restore and PITR test run `{{ run_id }}`

Generated by `make test-backups`. Every line below is output from the run — nothing here is written by hand.

- Cluster: kind `{{ kind_cluster_name }}`, namespace `{{ mysql_namespace }}`, Percona Operator for MySQL `{{ ps_operator_chart_version }}`
- MySQL: `{{ mysql_image }}`, {{ mysql_size }} nodes, async GTID replication
- Backup storage: MinIO bucket `{{ backup_bucket }}`; binlogs: `{{ binlog_bucket }}`
- Dataset: sysbench `{{ sysbench_tables }}` tables x `{{ sysbench_table_size }}` rows

## Summary

| # | Scenario | Result | Duration |
| --- | --- | --- | --- |
{% for r in results %}
| {{ r.scenario }} | {{ r.title }} | {{ '**PASS**' if r.status == 'passed' else '**FAIL**' }} | {{ r.duration_seconds }}s |
{% endfor %}

Passed {{ results | selectattr('status', 'equalto', 'passed') | list | length }} of {{ results | length }}.
Total scenario time: {{ results | map(attribute='duration_seconds') | sum }}s.

## Detail

{% for r in results %}
### {{ r.scenario }} — {{ r.title }}

Result: **{{ r.status | upper }}** in {{ r.duration_seconds }}s.

```
{% for line in r.evidence %}
{{ line }}
{% endfor %}
```

{% endfor %}
```

- [ ] **Step 7: Write the ordered runner and the report playbook**

`ansible/playbooks/tests/all.yml`:

```yaml
---
# Ordered backup/restore/PITR suite. Order is load-bearing: every restore
# needs a good backup behind it, and destructive scenarios must not strand
# the lab. Run with: make test-backups
- name: MySQL backup, restore and PITR suite
  hosts: localhost
  gather_facts: false
  vars:
    kubeconfig_path: "{{ (playbook_dir ~ '/../../..') | realpath }}/.kube/config"
  environment:
    PATH: "/opt/homebrew/bin:/usr/local/bin:{{ lookup('env', 'PATH') }}"
    KUBECONFIG: "{{ (playbook_dir ~ '/../../..') | realpath }}/.kube/config"
  roles:
    - test_common
    - t01_backup_full
    - t02_backup_from_replica
    - t03_backup_incremental
    - t04_storage_contents
    - t05_backup_scheduled
    - t06_backup_retention
    - t07_restore_in_place
    - t08_restore_dropped_table
    - t09_pitr_timestamp
    - t10_pitr_gtid
    - t11_pitr_invalid_target
    - t12_restore_as_replica
    - test_report
```

Note `../../..` — test playbooks sit one directory deeper than the existing ones.

`ansible/playbooks/tests/report.yml`:

```yaml
---
- name: Re-render the run report
  hosts: localhost
  gather_facts: false
  environment:
    PATH: "/opt/homebrew/bin:/usr/local/bin:{{ lookup('env', 'PATH') }}"
  roles:
    - test_common
    - test_report
```

`test_common` has no `tasks/main.yml`, so listing it as a role only loads its defaults — which is exactly what is wanted. Create an empty `ansible/roles/test_common/tasks/main.yml` containing `---` and a single `- name: test_common provides shared includes only` / `ansible.builtin.debug:` task so Ansible does not warn.

- [ ] **Step 8: Add the make and lab.sh targets**

In `Makefile`, add to `.PHONY` and to the body:

```make
RUN_ID ?= $(shell date -u +%Y%m%dT%H%M%SZ)

test-backups:
	cd ansible && ../$(ANSIBLE) playbooks/tests/all.yml -e run_id=$(RUN_ID)

report:
	cd ansible && ../$(ANSIBLE) playbooks/tests/report.yml -e run_id=$(RUN_ID)

test-t01:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t01-backup-full.yml -e run_id=$(RUN_ID)

test-t02:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t02-backup-from-replica.yml -e run_id=$(RUN_ID)

test-t03:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t03-backup-incremental.yml -e run_id=$(RUN_ID)

test-t04:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t04-storage-contents.yml -e run_id=$(RUN_ID)

test-t05:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t05-backup-scheduled.yml -e run_id=$(RUN_ID)

test-t06:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t06-backup-retention.yml -e run_id=$(RUN_ID)

test-t07:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t07-restore-in-place.yml -e run_id=$(RUN_ID)

test-t08:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t08-restore-dropped-table.yml -e run_id=$(RUN_ID)

test-t09:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t09-pitr-timestamp.yml -e run_id=$(RUN_ID)

test-t10:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t10-pitr-gtid.yml -e run_id=$(RUN_ID)

test-t11:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t11-pitr-invalid-target.yml -e run_id=$(RUN_ID)

test-t12:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t12-restore-as-replica.yml -e run_id=$(RUN_ID)
```

In `scripts/lab.sh`, add before the `*)` case:

```bash
  test-backups)
    (cd ansible && "$ANSIBLE" playbooks/tests/all.yml -e run_id="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}" "$@")
    ;;
  report)
    (cd ansible && "$ANSIBLE" playbooks/tests/report.yml -e run_id="${RUN_ID:?set RUN_ID}" "$@")
    ;;
  t0*|t1*)
    playbook=$(ls ansible/playbooks/tests/${cmd}-*.yml | head -1)
    (cd ansible && "$ANSIBLE" "${playbook#ansible/}" -e run_id="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}" "$@")
    ;;
```

and extend the usage string to `{bootstrap|test|deploy|load-data|verify|backup|restore|test-backups|t01..t12|report|teardown}`.

- [ ] **Step 9: Keep generated results out of noise but in git**

Add `docs/results/.gitkeep` (empty file). Do **not** gitignore `docs/results/` — the measured runs are the point of the lab and belong in the repository.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 11: Verify the harness parses standalone**

Run: `cd ansible && ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/report.yml`
Expected: no syntax errors. (`all.yml` will fail until the scenario roles exist — that is Task 4 onward.)

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "Add the backup test harness: result recording, health gate, report"
```

---

### Task 4: Scenarios 01–03 — the backup family

Three scenarios that prove backups are *produced*: a full backup, a backup taken from the replica rather than the primary, and an incremental backup on top of the full. This task also establishes the scenario role shape every later task copies.

**Files:**
- Create: `ansible/roles/test_common/tasks/mc.yml`
- Create: `ansible/roles/t01_backup_full/tasks/main.yml`, `ansible/playbooks/tests/t01-backup-full.yml`
- Create: `ansible/roles/t02_backup_from_replica/tasks/main.yml`, `ansible/playbooks/tests/t02-backup-from-replica.yml`
- Create: `ansible/roles/t03_backup_incremental/tasks/main.yml`, `ansible/playbooks/tests/t03-backup-incremental.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: `test_common/tasks/health_gate.yml`, `test_common/tasks/record_result.yml` (Task 3).
- Produces:
  - `test_common/tasks/mc.yml` — include with `vars: mc_args: "<shell using the mc binary>"`; runs it in a throwaway `minio/mc` pod with alias `local` already set, registers `mc_out`.
  - Backup objects named `t01-full`, `t02-replica`, `t03-incr` left in the namespace. Task 5 scenario 04 reads their `status.destination`; Task 8 scenario 12 takes its own backup and does not depend on these.
  - The scenario role shape: `set_fact t_start` → `block` (health gate, work, asserts, record passed) → `rescue` (record failed, re-fail).

- [ ] **Step 1: Write the failing structural test**

Add to `tests/test_lab_config.py`:

```python
    def test_every_scenario_has_a_role_and_playbook(self) -> None:
        for sid, slug in self.SCENARIOS[:3]:
            role = ANSIBLE / "roles" / f"{sid}_{slug.replace('-', '_')}" / "tasks" / "main.yml"
            play = PLAYBOOKS / "tests" / f"{sid}-{slug}.yml"
            self.assertTrue(role.is_file(), f"missing role tasks for {sid}")
            self.assertTrue(play.is_file(), f"missing playbook for {sid}")
            text = role.read_text()
            self.assertIn("record_result.yml", text)
            self.assertIn("rescue", text)
            self.assertIn(f"scenario_id: {sid}", text)

    def test_backup_scenarios_cover_full_replica_and_incremental(self) -> None:
        t01 = (ANSIBLE / "roles" / "t01_backup_full" / "tasks" / "main.yml").read_text()
        self.assertIn("type: full", t01)
        t02 = (ANSIBLE / "roles" / "t02_backup_from_replica" / "tasks" / "main.yml").read_text()
        self.assertIn("sourcePod", t02)
        t03 = (ANSIBLE / "roles" / "t03_backup_incremental" / "tasks" / "main.yml").read_text()
        self.assertIn("type: incremental", t03)
        self.assertIn("incrementalBaseBackupName", t03)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — missing role tasks for t01.

- [ ] **Step 3: Write the mc helper**

`ansible/roles/test_common/tasks/mc.yml`:

```yaml
---
# Runs `mc_args` in a throwaway minio/mc pod with the `local` alias configured.
# Callers pass: mc_args, e.g. "mc ls --recursive local/mysql-lab-backups"
- name: "mc: {{ mc_args }}"
  ansible.builtin.shell: |
    set -euo pipefail
    export KUBECONFIG="{{ kubeconfig_path }}"
    kubectl -n {{ mysql_namespace }} run mc-$RANDOM --rm -i --restart=Never --quiet \
      --image={{ minio_mc_image }} --command -- sh -c \
      'mc alias set local http://minio:9000 {{ minio_root_user }} {{ minio_root_password }} >/dev/null 2>&1; {{ mc_args }}'
  args:
    executable: /bin/bash
  register: mc_out
  changed_when: false
  retries: 3
  delay: 5
  until: mc_out.rc == 0
```

- [ ] **Step 4: Write the t01 role**

`ansible/roles/t01_backup_full/tasks/main.yml`:

```yaml
---
- name: Start the t01 clock
  ansible.builtin.set_fact:
    t_start: "{{ lookup('pipe', 'date -u +%s') }}"

- block:
    - name: Gate on cluster health before t01
      ansible.builtin.include_tasks: ../../test_common/tasks/health_gate.yml

    - name: Remove any stale t01 backup object
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t01-full
        wait: true
        wait_timeout: 180

    - name: Record the dataset the backup will capture
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT CONCAT('TABLES=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name LIKE 'sbtest%';
           SELECT CONCAT('SIZE_MB=', IFNULL(ROUND(SUM(data_length+index_length)/1024/1024),0))
             FROM information_schema.tables WHERE table_schema='{{ sysbench_database }}';
           SELECT CONCAT('GTID_AT_BACKUP=', @@GLOBAL.gtid_executed);" | tr -d '\r'
      args:
        executable: /bin/bash
      register: pre
      changed_when: false

    - name: Request a full backup
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLBackup
          metadata:
            name: t01-full
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            storageName: "{{ backup_storage_name }}"
            type: full

    - name: Wait for the full backup to finish
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t01-full
      register: t01_bkp
      until:
        - t01_bkp.resources | length == 1
        - (t01_bkp.resources[0].status.state | default('') | lower)
          in ['succeeded', 'ready', 'done', 'failed', 'error']
      retries: 120
      delay: 10

    - name: Require the full backup to have succeeded
      ansible.builtin.assert:
        that:
          - (t01_bkp.resources[0].status.state | default('') | lower) in ['succeeded', 'ready', 'done']
          - t01_bkp.resources[0].status.destination | default('') | length > 0
          - backup_bucket in t01_bkp.resources[0].status.destination
        fail_msg: "Full backup did not succeed: {{ t01_bkp.resources[0].status | default({}) }}"

    - name: Measure the backup in MinIO
      ansible.builtin.include_tasks: ../../test_common/tasks/mc.yml
      vars:
        mc_args: "mc du local/{{ backup_bucket }}/{{ mysql_cluster_name }} 2>/dev/null | tail -1"

    - name: Assemble the t01 evidence
      ansible.builtin.set_fact:
        t01_evidence: >-
          {{ pre.stdout_lines
             + ['BACKUP_STATE=' ~ t01_bkp.resources[0].status.state]
             + ['BACKUP_TYPE=' ~ (t01_bkp.resources[0].status.type | default('full'))]
             + ['BACKUP_DESTINATION=' ~ t01_bkp.resources[0].status.destination]
             + ['BACKUP_COMPLETED=' ~ (t01_bkp.resources[0].status.completed | default('n/a'))]
             + ['MINIO_USAGE=' ~ (mc_out.stdout | trim)] }}

    - name: Record t01 as passed
      ansible.builtin.include_tasks: ../../test_common/tasks/record_result.yml
      vars:
        scenario_id: t01
        scenario_title: On-demand full backup to MinIO
        scenario_status: passed
        scenario_started: "{{ t_start }}"
        scenario_evidence: "{{ t01_evidence }}"

  rescue:
    - name: Record t01 as failed
      ansible.builtin.include_tasks: ../../test_common/tasks/record_result.yml
      vars:
        scenario_id: t01
        scenario_title: On-demand full backup to MinIO
        scenario_status: failed
        scenario_started: "{{ t_start }}"
        scenario_evidence: "{{ ansible_failed_result.msg | default('see play output') | string | split('\n') }}"

    - name: Fail the play after recording t01
      ansible.builtin.fail:
        msg: "t01 failed: {{ ansible_failed_result.msg | default('see above') }}"
```

Note the relative `include_tasks` paths: a role's `tasks/main.yml` resolves relative includes from its own `tasks/` directory, so `../../test_common/tasks/x.yml` reaches the sibling role. If Ansible rejects that in practice, replace those includes with `ansible.builtin.include_role: {name: test_common, tasks_from: x.yml}` and keep the same `vars:` block — behaviour is identical.

- [ ] **Step 5: Write the t01 playbook**

`ansible/playbooks/tests/t01-backup-full.yml`:

```yaml
---
- name: "t01 — on-demand full backup"
  hosts: localhost
  gather_facts: false
  vars:
    kubeconfig_path: "{{ (playbook_dir ~ '/../../..') | realpath }}/.kube/config"
  environment:
    PATH: "/opt/homebrew/bin:/usr/local/bin:{{ lookup('env', 'PATH') }}"
    KUBECONFIG: "{{ (playbook_dir ~ '/../../..') | realpath }}/.kube/config"
  roles:
    - test_common
    - t01_backup_full
```

Every later scenario playbook is this file with the name, comment and second role changed. Write each one out in full rather than copying by reference.

- [ ] **Step 6: Run t01 against the live cluster is deferred**

The cluster is redeployed in Task 9; scenarios are executed there. For now:

Run: `cd ansible && ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/t01-backup-full.yml`
Expected: no syntax errors.

- [ ] **Step 7: Write the t02 role — backup from the replica**

`ansible/roles/t02_backup_from_replica/tasks/main.yml`. Same shape as t01 with these differences:

- Before requesting the backup, resolve the replica pod and confirm it is read-only:

```yaml
    - name: Find a read-only replica to back up from
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        for p in $(kubectl -n "$NS" get pods -l app.kubernetes.io/instance={{ mysql_cluster_name }},app.kubernetes.io/component=database \
          -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort); do
          ro=$(kubectl -n "$NS" exec "$p" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "SELECT @@read_only" 2>/dev/null | tr -d '\r')
          if [ "$ro" = "1" ]; then echo "$p"; exit 0; fi
        done
        exit 1
      args:
        executable: /bin/bash
      register: replica_pod
      changed_when: false
```

- The backup definition is:

```yaml
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            storageName: "{{ backup_storage_name }}"
            type: full
            sourcePod: "{{ replica_pod.stdout | trim }}"
```

named `t02-replica`.

- After the backup succeeds, prove the primary served writes the whole time:

```yaml
    - name: Confirm the primary stayed writable during the replica backup
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "CREATE TABLE IF NOT EXISTS {{ sysbench_database }}.t02_writes (id INT AUTO_INCREMENT PRIMARY KEY, at DATETIME);
           INSERT INTO {{ sysbench_database }}.t02_writes (at) VALUES (UTC_TIMESTAMP());
           SELECT CONCAT('PRIMARY_WRITABLE=', IF(@@read_only=0,'yes','no'));
           SELECT CONCAT('PRIMARY_WRITES=', COUNT(*)) FROM {{ sysbench_database }}.t02_writes;" | tr -d '\r'
      args:
        executable: /bin/bash
      register: primary_writes
      changed_when: true
```

- Assertions: backup state succeeded; `status.destination` contains the bucket; the resolved source pod is not `-mysql-0`; `PRIMARY_WRITABLE=yes`.
- Evidence: `SOURCE_POD=<pod>`, backup state, destination, plus `primary_writes.stdout_lines`.
- `scenario_id: t02`, `scenario_title: Backup taken from the replica, primary untouched`.

- [ ] **Step 8: Write the t02 playbook**

`ansible/playbooks/tests/t02-backup-from-replica.yml` — the Step 5 file with `name: "t02 — backup from the replica"` and roles `test_common`, `t02_backup_from_replica`.

- [ ] **Step 9: Write the t03 role — incremental on the full base**

`ansible/roles/t03_backup_incremental/tasks/main.yml`. Same shape, with:

- A guard that the base exists:

```yaml
    - name: Require the t01 full backup as the incremental base
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t01-full
      register: t03_base
      failed_when:
        - (t03_base.resources | default([]) | length) == 0
          or (t03_base.resources[0].status.state | default('') | lower) not in ['succeeded', 'ready', 'done']
```

- Write a known quantity of new data first, so the incremental has something to carry and the size comparison is meaningful:

```yaml
    - name: Write 50k new rows since the base backup
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "CREATE TABLE IF NOT EXISTS {{ sysbench_database }}.t03_delta (id INT AUTO_INCREMENT PRIMARY KEY, pad CHAR(120));
           INSERT INTO {{ sysbench_database }}.t03_delta (pad)
             SELECT LEFT(MD5(RAND()), 120) FROM {{ sysbench_database }}.sbtest1 LIMIT 50000;
           SELECT CONCAT('DELTA_ROWS=', COUNT(*)) FROM {{ sysbench_database }}.t03_delta;" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t03_delta
      changed_when: true
```

- The backup definition, named `t03-incr`:

```yaml
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            storageName: "{{ backup_storage_name }}"
            type: incremental
            incrementalBaseBackupName: t01-full
```

- After success, size both destinations with `mc du` (two includes of `mc.yml`, registering into distinct facts by copying `mc_out.stdout` into `t03_full_du` and `t03_incr_du` with `set_fact` right after each include; `mc_out` is overwritten by the second call).
- Assertions: state succeeded; `status.type` is `incremental`; the incremental's byte count is strictly less than the full's. Parse the leading integer of `mc du --json`-free output by taking `mc du` first field, e.g. `471MiB`; to compare reliably, use `mc du --json` and parse `size`:

```yaml
      vars:
        mc_args: "mc du --json local/{{ backup_bucket }}/<prefix> | tail -1"
```

then `(t03_incr_du | from_json).size < (t03_full_du | from_json).size`. Derive `<prefix>` from each backup's `status.destination` by stripping the `s3://{{ backup_bucket }}/` scheme:

```yaml
    - name: Derive the MinIO prefixes for both backups
      ansible.builtin.set_fact:
        t03_full_prefix: "{{ t03_base.resources[0].status.destination | regex_replace('^s3://' ~ backup_bucket ~ '/', '') }}"
        t03_incr_prefix: "{{ t03_bkp.resources[0].status.destination | regex_replace('^s3://' ~ backup_bucket ~ '/', '') }}"
```

If `status.destination` turns out not to carry an `s3://` scheme on this operator version, adjust the regex to whatever the recorded destination actually looks like — Task 9 is where that is confirmed against real output.

- `scenario_id: t03`, `scenario_title: Incremental backup on a full base`.
- Evidence: delta rows, both destinations, both byte counts, and the ratio.

- [ ] **Step 10: Write the t03 playbook**

`ansible/playbooks/tests/t03-backup-incremental.yml` — Step 5's file with `t03_backup_incremental`.

- [ ] **Step 11: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 12: Syntax-check all three**

Run: `cd ansible && for p in t01-backup-full t02-backup-from-replica t03-backup-incremental; do ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/$p.yml; done`
Expected: no syntax errors.

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "Add backup scenarios: full, from replica, incremental"
```

---

### Task 5: Scenarios 04–06 — storage, schedule and retention

Three scenarios that prove the backups exist as objects, that the operator's cron produces them unattended, and that `keep` actually prunes.

**Files:**
- Create: `ansible/roles/t04_storage_contents/tasks/main.yml`, `ansible/playbooks/tests/t04-storage-contents.yml`
- Create: `ansible/roles/t05_backup_scheduled/tasks/main.yml`, `ansible/playbooks/tests/t05-backup-scheduled.yml`
- Create: `ansible/roles/t06_backup_retention/tasks/main.yml`, `ansible/playbooks/tests/t06-backup-retention.yml`
- Modify: `ansible/inventory/group_vars/all.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: `mc.yml`, `health_gate.yml`, `record_result.yml`; the backup objects from Task 4.
- Produces: vars `suite_fast_schedule: "*/3 * * * *"`, `suite_fast_keep: 2`, `suite_schedule_name: suite-fast`. Scenarios 05 and 06 both patch `spec.backup.schedule` to a single fast entry and restore the shipped schedule in an `always` block.

- [ ] **Step 1: Write the failing structural test**

Extend the Task 4 test to cover the first six scenarios and add:

```python
    def test_schedule_scenarios_restore_the_shipped_schedule(self) -> None:
        v = load_group_vars()
        self.assertEqual(v["suite_schedule_name"], "suite-fast")
        self.assertEqual(int(v["suite_fast_keep"]), 2)
        for sid in ("t05_backup_scheduled", "t06_backup_retention"):
            text = (ANSIBLE / "roles" / sid / "tasks" / "main.yml").read_text()
            self.assertIn("always:", text)
            self.assertIn("backup_schedule", text)
            self.assertIn("xb-cron", text)
```

Change `self.SCENARIOS[:3]` to `self.SCENARIOS[:6]` in `test_every_scenario_has_a_role_and_playbook`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `KeyError: 'suite_schedule_name'`.

- [ ] **Step 3: Add the schedule variables**

Append to `ansible/inventory/group_vars/all.yml`:

```yaml
suite_schedule_name: suite-fast
suite_fast_schedule: "*/3 * * * *"
suite_fast_keep: 2
```

- [ ] **Step 4: Write the t04 role — storage contents**

`ansible/roles/t04_storage_contents/tasks/main.yml`, standard shape, body:

```yaml
    - name: List the backup bucket
      ansible.builtin.include_tasks: ../../test_common/tasks/mc.yml
      vars:
        mc_args: "mc ls --recursive local/{{ backup_bucket }}"

    - name: Keep the backup listing
      ansible.builtin.set_fact:
        t04_backup_ls: "{{ mc_out.stdout_lines }}"

    - name: Count binlog objects, wait, count again
      ansible.builtin.include_tasks: ../../test_common/tasks/mc.yml
      vars:
        mc_args: >-
          mc ls --recursive local/{{ binlog_bucket }} | wc -l;
          sleep 90;
          mc ls --recursive local/{{ binlog_bucket }} | wc -l;
          mc ls --recursive local/{{ binlog_bucket }} | tail -5

    - name: Keep the binlog listing
      ansible.builtin.set_fact:
        t04_binlog_ls: "{{ mc_out.stdout_lines }}"

    - name: Require real backup objects and a live binlog stream
      ansible.builtin.assert:
        that:
          - t04_backup_ls | select('search', 'xtrabackup') | list | length > 0
          - t04_backup_ls | select('search', ' 0B ') | list | length == 0
          - (t04_binlog_ls | select('match', '^[0-9]+$') | list | first | int) > 0
          - (t04_binlog_ls | select('match', '^[0-9]+$') | list | last | int)
            >= (t04_binlog_ls | select('match', '^[0-9]+$') | list | first | int)
        fail_msg: >-
          Storage does not look right. backups={{ t04_backup_ls }} binlogs={{ t04_binlog_ls }}
```

The 90-second wait is deliberate: `binlog_checkpoint_interval` is 30s, so a live stream must have written at least one more object by then. The assertion is `>=` rather than `>` because a fully idle server may legitimately not roll a new object; the `> 0` first count is what proves streaming works at all. If the count never moves while writes are happening, that is a real finding for Task 9 to chase.

- `scenario_id: t04`, `scenario_title: Backup and binlog objects present in MinIO`.
- Evidence: `t04_backup_ls + t04_binlog_ls`.

- [ ] **Step 5: Write the t05 role — scheduled backup**

`ansible/roles/t05_backup_scheduled/tasks/main.yml`:

```yaml
---
- name: Start the t05 clock
  ansible.builtin.set_fact:
    t_start: "{{ lookup('pipe', 'date -u +%s') }}"
    t05_seen_before: []

- block:
    - name: Gate on cluster health before t05
      ansible.builtin.include_tasks: ../../test_common/tasks/health_gate.yml

    - name: Note the cron backups that already exist
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
      register: t05_before

    - name: Remember their names
      ansible.builtin.set_fact:
        t05_seen_before: "{{ t05_before.resources | map(attribute='metadata.name') | select('match', '^xb-cron-') | list }}"

    - name: Patch the cluster to a fast backup schedule
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: patched
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQL
        namespace: "{{ mysql_namespace }}"
        name: "{{ mysql_cluster_name }}"
        definition:
          spec:
            backup:
              schedule:
                - name: "{{ suite_schedule_name }}"
                  schedule: "{{ suite_fast_schedule }}"
                  keep: "{{ backup_keep }}"
                  storageName: "{{ backup_storage_name }}"
                  type: full

    - name: Wait for the cron to create and finish a new backup
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
      register: t05_after
      until: >-
        (t05_after.resources
          | selectattr('metadata.name', 'match', '^xb-cron-')
          | rejectattr('metadata.name', 'in', t05_seen_before)
          | selectattr('status.state', 'defined')
          | selectattr('status.state', 'match', '(?i)^(succeeded|ready|done)$')
          | list | length) >= 1
      retries: 60
      delay: 15

    - name: Describe the new scheduled backup
      ansible.builtin.set_fact:
        t05_new: >-
          {{ (t05_after.resources
              | selectattr('metadata.name', 'match', '^xb-cron-')
              | rejectattr('metadata.name', 'in', t05_seen_before)
              | selectattr('status.state', 'defined')
              | selectattr('status.state', 'match', '(?i)^(succeeded|ready|done)$')
              | list | first) }}

    - name: Require the scheduled backup to be a real backup
      ansible.builtin.assert:
        that:
          - t05_new.metadata.name is search(suite_schedule_name) or t05_new.metadata.name is match('^xb-cron-')
          - backup_bucket in (t05_new.status.destination | default(''))
        fail_msg: "Scheduled backup looks wrong: {{ t05_new }}"

    - name: Record t05 as passed
      ansible.builtin.include_tasks: ../../test_common/tasks/record_result.yml
      vars:
        scenario_id: t05
        scenario_title: Scheduled backup runs unattended
        scenario_status: passed
        scenario_started: "{{ t_start }}"
        scenario_evidence:
          - "SCHEDULE_PATCHED={{ suite_fast_schedule }}"
          - "PRE_EXISTING_CRON_BACKUPS={{ t05_seen_before | length }}"
          - "NEW_BACKUP={{ t05_new.metadata.name }}"
          - "NEW_BACKUP_STATE={{ t05_new.status.state }}"
          - "NEW_BACKUP_DESTINATION={{ t05_new.status.destination | default('n/a') }}"
          - "NEW_BACKUP_COMPLETED={{ t05_new.status.completed | default('n/a') }}"

  rescue:
    - name: Record t05 as failed
      ansible.builtin.include_tasks: ../../test_common/tasks/record_result.yml
      vars:
        scenario_id: t05
        scenario_title: Scheduled backup runs unattended
        scenario_status: failed
        scenario_started: "{{ t_start }}"
        scenario_evidence: "{{ ansible_failed_result.msg | default('see play output') | string | split('\n') }}"

    - name: Fail the play after recording t05
      ansible.builtin.fail:
        msg: "t05 failed: {{ ansible_failed_result.msg | default('see above') }}"

  always:
    - name: Restore the shipped backup schedule
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: patched
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQL
        namespace: "{{ mysql_namespace }}"
        name: "{{ mysql_cluster_name }}"
        definition:
          spec:
            backup:
              schedule:
                - name: hourly-full
                  schedule: "{{ backup_schedule }}"
                  keep: "{{ backup_keep }}"
                  storageName: "{{ backup_storage_name }}"
                  type: full
```

- [ ] **Step 6: Write the t06 role — retention**

`ansible/roles/t06_backup_retention/tasks/main.yml`, same structure as t05, with `keep: "{{ suite_fast_keep }}"` in the patch and this as the body between patch and restore:

```yaml
    - name: Wait for more cron backups than keep allows
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        label_selectors:
          - percona.com/backup-ancestor={{ suite_schedule_name }}
      register: t06_cron
      until: >-
        (t06_cron.resources
          | selectattr('status.state', 'defined')
          | selectattr('status.state', 'match', '(?i)^(succeeded|ready|done)$')
          | list | length) >= ((suite_fast_keep | int) + 1)
      retries: 80
      delay: 15
      failed_when: false

    - name: Fall back to name matching if the ancestor label is absent
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
      register: t06_all
      until: >-
        (t06_all.resources
          | selectattr('metadata.name', 'search', suite_schedule_name)
          | selectattr('status.state', 'defined')
          | selectattr('status.state', 'match', '(?i)^(succeeded|ready|done)$')
          | list | length) >= ((suite_fast_keep | int) + 1)
      retries: 80
      delay: 15
      when: (t06_cron.resources | default([]) | length) == 0

    - name: Give the operator a pruning cycle
      ansible.builtin.pause:
        seconds: 200

    - name: Count what survived
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
      register: t06_final

    - name: List the backup bucket after pruning
      ansible.builtin.include_tasks: ../../test_common/tasks/mc.yml
      vars:
        mc_args: "mc ls local/{{ backup_bucket }}/{{ mysql_cluster_name }} | wc -l; mc ls local/{{ backup_bucket }}/{{ mysql_cluster_name }}"

    - name: Require retention to have pruned down to keep
      ansible.builtin.set_fact:
        t06_surviving: >-
          {{ t06_final.resources
             | selectattr('metadata.name', 'search', suite_schedule_name)
             | map(attribute='metadata.name') | list }}

    - name: Assert the surviving count matches keep
      ansible.builtin.assert:
        that:
          - (t06_surviving | length) <= (suite_fast_keep | int)
        fail_msg: >-
          Retention did not prune: keep={{ suite_fast_keep }} surviving={{ t06_surviving }}
```

- Evidence: the observed backup names before pruning, the surviving names, the keep value, and the `mc ls` output.
- `scenario_id: t06`, `scenario_title: Retention prunes scheduled backups down to keep`.

The 200-second pause is because the operator prunes on its own reconcile cadence, not instantly. If Task 9 shows pruning takes longer, raise it there and record the real number in the documentation.

- [ ] **Step 7: Write the three playbooks**

`ansible/playbooks/tests/t04-storage-contents.yml`, `t05-backup-scheduled.yml`, `t06-backup-retention.yml` — the Task 4 Step 5 file, each with its own `name:` and its own second role.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 9: Syntax-check**

Run: `cd ansible && for p in t04-storage-contents t05-backup-scheduled t06-backup-retention; do ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/$p.yml; done`
Expected: no syntax errors.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Add storage, scheduled backup and retention scenarios"
```

---

### Task 6: Scenarios 07–08 — restore in place

The first two scenarios that prove a backup restores: a whole-cluster restore that must roll back a canary, and a dropped-table disaster.

**Files:**
- Create: `ansible/roles/t07_restore_in_place/tasks/main.yml`, `ansible/playbooks/tests/t07-restore-in-place.yml`
- Create: `ansible/roles/t08_restore_dropped_table/tasks/main.yml`, `ansible/playbooks/tests/t08-restore-dropped-table.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: `t01-full` backup, the shared includes.
- Produces: restore objects `t07-restore` and `t08-restore`. Both delete any same-named predecessor first, so scenarios are re-runnable.

- [ ] **Step 1: Write the failing structural test**

Change `self.SCENARIOS[:6]` to `self.SCENARIOS[:8]` and add:

```python
    def test_restore_scenarios_prove_rollback(self) -> None:
        t07 = (ANSIBLE / "roles" / "t07_restore_in_place" / "tasks" / "main.yml").read_text()
        self.assertIn("canary", t07)
        self.assertIn("PerconaServerMySQLRestore", t07)
        t08 = (ANSIBLE / "roles" / "t08_restore_dropped_table" / "tasks" / "main.yml").read_text()
        self.assertIn("DROP TABLE", t08)
        self.assertIn("sbtest10", t08)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — missing role tasks for t07.

- [ ] **Step 3: Write the t07 role**

`ansible/roles/t07_restore_in_place/tasks/main.yml`, standard shape, body:

```yaml
    - name: Find the writable primary
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        for p in $(kubectl -n "$NS" get pods -l app.kubernetes.io/instance={{ mysql_cluster_name }},app.kubernetes.io/component=database \
          -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort); do
          ro=$(kubectl -n "$NS" exec "$p" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "SELECT @@read_only" 2>/dev/null | tr -d '\r')
          if [ "$ro" = "0" ]; then echo "$p"; exit 0; fi
        done
        exit 1
      args:
        executable: /bin/bash
      register: t07_primary
      changed_when: false

    - name: Create a canary that the backup cannot contain
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ t07_primary.stdout | trim }} -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "CREATE TABLE IF NOT EXISTS {{ sysbench_database }}.canary_after_backup (id INT PRIMARY KEY, note VARCHAR(64));
           INSERT INTO {{ sysbench_database }}.canary_after_backup VALUES (1,'written after the backup')
             ON DUPLICATE KEY UPDATE note=VALUES(note);
           SELECT CONCAT('CANARY_BEFORE_RESTORE=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name='canary_after_backup';" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t07_canary
      changed_when: true

    - name: Require the canary to exist before restoring
      ansible.builtin.assert:
        that:
          - "'CANARY_BEFORE_RESTORE=1' in t07_canary.stdout"

    - name: Remove any stale t07 restore object
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t07-restore
        wait: true
        wait_timeout: 180

    - name: Restore the full backup over the running cluster
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLRestore
          metadata:
            name: t07-restore
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            backupName: t01-full

    - name: Wait for the restore to finish
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t07-restore
      register: t07_rst
      until:
        - t07_rst.resources | length == 1
        - (t07_rst.resources[0].status.state | default('') | lower)
          in ['succeeded', 'ready', 'done', 'failed', 'error']
      retries: 160
      delay: 15

    - name: Require the restore to have succeeded
      ansible.builtin.assert:
        that:
          - (t07_rst.resources[0].status.state | default('') | lower) in ['succeeded', 'ready', 'done']
        fail_msg: "Restore failed: {{ t07_rst.resources[0].status | default({}) }}"

    - name: Gate on cluster health after the restore
      ansible.builtin.include_tasks: ../../test_common/tasks/health_gate.yml

    - name: Measure the restored dataset
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT CONCAT('RESTORED_TABLES=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name LIKE 'sbtest%';
           SELECT CONCAT('RESTORED_SIZE_MB=', IFNULL(ROUND(SUM(data_length+index_length)/1024/1024),0))
             FROM information_schema.tables WHERE table_schema='{{ sysbench_database }}';
           SELECT CONCAT('CANARY_AFTER_RESTORE=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name='canary_after_backup';" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t07_after
      changed_when: false
      retries: 20
      delay: 15
      until: t07_after.rc == 0

    - name: Require the dataset back and the canary gone
      ansible.builtin.assert:
        that:
          - "'RESTORED_TABLES=' ~ sysbench_tables in t07_after.stdout"
          - "'CANARY_AFTER_RESTORE=0' in t07_after.stdout"
          - (t07_after.stdout_lines | select('match', '^RESTORED_SIZE_MB=') | first).split('=')[1] | int
            >= (data_size_min_mb | int)
        fail_msg: "Restore did not roll the cluster back: {{ t07_after.stdout }}"
```

- `scenario_id: t07`, `scenario_title: Whole-cluster restore rolls back post-backup writes`.
- Evidence: `t07_canary.stdout_lines + ['RESTORE_STATE=' ~ state] + t07_after.stdout_lines + ['HEALTH=' ~ health_summary]`.

- [ ] **Step 4: Write the t08 role**

`ansible/roles/t08_restore_dropped_table/tasks/main.yml`. Same shape as t07, differing in the damage and the assertions:

```yaml
    - name: Record sbtest10 before dropping it
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ t08_primary.stdout | trim }} -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT CONCAT('ROWS_BEFORE_DROP=', COUNT(*)) FROM {{ sysbench_database }}.sbtest10;" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t08_before
      changed_when: false

    - name: Drop the table, as a tired human would at 02:00
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ t08_primary.stdout | trim }} -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "DROP TABLE {{ sysbench_database }}.sbtest10;
           SELECT CONCAT('TABLES_AFTER_DROP=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name LIKE 'sbtest%';" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t08_drop
      changed_when: true

    - name: Require the table to actually be gone
      ansible.builtin.assert:
        that:
          - "'TABLES_AFTER_DROP=' ~ ((sysbench_tables | int) - 1) in t08_drop.stdout"
```

Then the same restore block with names `t08-restore` and `backupName: t01-full`, the health gate, and:

```yaml
    - name: Require sbtest10 back with its rows
      ansible.builtin.assert:
        that:
          - "'TABLES_AFTER_RESTORE=' ~ sysbench_tables in t08_after.stdout"
          - (t08_after.stdout_lines | select('match', '^ROWS_AFTER_RESTORE=') | first).split('=')[1] | int
            == (t08_before.stdout_lines | select('match', '^ROWS_BEFORE_DROP=') | first).split('=')[1] | int
        fail_msg: "Dropped table did not come back intact: {{ t08_after.stdout }}"
```

where `t08_after` queries `TABLES_AFTER_RESTORE` and `ROWS_AFTER_RESTORE` the same way t07's measurement task does.

- `scenario_id: t08`, `scenario_title: Restore recovers a dropped table`.

- [ ] **Step 5: Write the two playbooks**

`ansible/playbooks/tests/t07-restore-in-place.yml` and `t08-restore-dropped-table.yml`, following Task 4 Step 5.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 7: Syntax-check**

Run: `cd ansible && for p in t07-restore-in-place t08-restore-dropped-table; do ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/$p.yml; done`
Expected: no syntax errors.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add in-place restore scenarios: canary rollback and dropped table"
```

---

### Task 7: Scenarios 09–11 — point in time recovery

Recovery to a wall-clock instant, recovery to a GTID, and a negative case proving an impossible target fails loudly instead of silently restoring the wrong thing.

**Files:**
- Create: `ansible/roles/t09_pitr_timestamp/tasks/main.yml`, `ansible/playbooks/tests/t09-pitr-timestamp.yml`
- Create: `ansible/roles/t10_pitr_gtid/tasks/main.yml`, `ansible/playbooks/tests/t10-pitr-gtid.yml`
- Create: `ansible/roles/t11_pitr_invalid_target/tasks/main.yml`, `ansible/playbooks/tests/t11-pitr-invalid-target.yml`
- Modify: `ansible/inventory/group_vars/all.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: the shared includes; the binlog server from Task 2.
- Produces: var `pitr_settle_seconds: 120` — how long a scenario waits after writing markers so the binlog server has certainly checkpointed them to MinIO. Every PITR scenario takes its **own** fresh full backup (`t09-base`, `t10-base`, `t11-base`) rather than reusing `t01-full`, because a PITR target must lie after its base backup and the earlier scenarios have already restored the cluster twice.

- [ ] **Step 1: Write the failing structural test**

Change `self.SCENARIOS[:8]` to `self.SCENARIOS[:11]` and add:

```python
    def test_pitr_scenarios_use_both_target_types(self) -> None:
        v = load_group_vars()
        self.assertGreaterEqual(int(v["pitr_settle_seconds"]), 60)
        t09 = (ANSIBLE / "roles" / "t09_pitr_timestamp" / "tasks" / "main.yml").read_text()
        self.assertIn("type: date", t09)
        self.assertIn("UTC_TIMESTAMP", t09)
        t10 = (ANSIBLE / "roles" / "t10_pitr_gtid" / "tasks" / "main.yml").read_text()
        self.assertIn("type: gtid", t10)
        self.assertIn("gtid_executed", t10)
        t11 = (ANSIBLE / "roles" / "t11_pitr_invalid_target" / "tasks" / "main.yml").read_text()
        self.assertIn("failed", t11)
        self.assertIn("health_gate.yml", t11)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `KeyError: 'pitr_settle_seconds'`.

- [ ] **Step 3: Add the settle variable**

Append to `ansible/inventory/group_vars/all.yml`:

```yaml
pitr_settle_seconds: 120
```

- [ ] **Step 4: Write the t09 role — recover to a timestamp**

`ansible/roles/t09_pitr_timestamp/tasks/main.yml`, standard shape, body:

```yaml
    - name: Take a fresh base backup for the PITR window
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t09-base
        wait: true
        wait_timeout: 180

    - name: Request the t09 base backup
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLBackup
          metadata:
            name: t09-base
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            storageName: "{{ backup_storage_name }}"
            type: full

    - name: Wait for the t09 base backup
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t09-base
      register: t09_base
      until:
        - t09_base.resources | length == 1
        - (t09_base.resources[0].status.state | default('') | lower)
          in ['succeeded', 'ready', 'done', 'failed', 'error']
      retries: 120
      delay: 10

    - name: Require the base backup
      ansible.builtin.assert:
        that:
          - (t09_base.resources[0].status.state | default('') | lower) in ['succeeded', 'ready', 'done']
        fail_msg: "t09 base backup failed: {{ t09_base.resources[0].status | default({}) }}"

    - name: Find the writable primary
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        for p in $(kubectl -n "$NS" get pods -l app.kubernetes.io/instance={{ mysql_cluster_name }},app.kubernetes.io/component=database \
          -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort); do
          ro=$(kubectl -n "$NS" exec "$p" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "SELECT @@read_only" 2>/dev/null | tr -d '\r')
          if [ "$ro" = "0" ]; then echo "$p"; exit 0; fi
        done
        exit 1
      args:
        executable: /bin/bash
      register: t09_primary
      changed_when: false

    - name: Write the "good" marker, capture the recovery target, then write the "bad" marker
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        POD="{{ t09_primary.stdout | trim }}"
        q() { kubectl -n "$NS" exec "$POD" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "$1" | tr -d '\r'; }
        q "CREATE TABLE IF NOT EXISTS {{ sysbench_database }}.pitr_markers
             (id INT AUTO_INCREMENT PRIMARY KEY, label VARCHAR(32), at DATETIME(6))"
        q "DELETE FROM {{ sysbench_database }}.pitr_markers"
        q "INSERT INTO {{ sysbench_database }}.pitr_markers (label, at) VALUES ('good', UTC_TIMESTAMP(6))"
        echo "GOOD_MARKER_AT=$(q "SELECT MAX(at) FROM {{ sysbench_database }}.pitr_markers WHERE label='good'")"
        sleep 20
        # The recovery target: after 'good', before 'bad'.
        echo "PITR_TARGET=$(q "SELECT DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%dT%H:%i:%sZ')")"
        sleep 20
        q "INSERT INTO {{ sysbench_database }}.pitr_markers (label, at) VALUES ('bad', UTC_TIMESTAMP(6))"
        echo "BAD_MARKER_AT=$(q "SELECT MAX(at) FROM {{ sysbench_database }}.pitr_markers WHERE label='bad'")"
        echo "MARKERS_BEFORE_RESTORE=$(q "SELECT GROUP_CONCAT(label ORDER BY id) FROM {{ sysbench_database }}.pitr_markers")"
      args:
        executable: /bin/bash
      register: t09_markers
      changed_when: true

    - name: Let the binlog server checkpoint both markers to MinIO
      ansible.builtin.pause:
        seconds: "{{ pitr_settle_seconds }}"

    - name: Extract the recovery target
      ansible.builtin.set_fact:
        t09_target: >-
          {{ (t09_markers.stdout_lines | select('match', '^PITR_TARGET=') | first).split('=')[1] }}

    - name: Remove any stale t09 restore object
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t09-restore
        wait: true
        wait_timeout: 180

    - name: Recover to the captured timestamp
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLRestore
          metadata:
            name: t09-restore
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            backupName: t09-base
            pitr:
              type: date
              date: "{{ t09_target }}"
              backupSource:
                binlogServer:
                  image: "{{ binlog_server_image }}"
                  serverId: "{{ binlog_server_id | int + 10 }}"
                  storage:
                    s3:
                      bucket: "{{ binlog_bucket }}"
                      credentialsSecret: "{{ minio_credentials_secret }}"
                      endpointUrl: "http://minio.{{ mysql_namespace }}.svc.cluster.local:9000"
                      region: us-east-1
                      prefix: "{{ binlog_prefix }}"

    - name: Wait for the PITR restore to finish
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t09-restore
      register: t09_rst
      until:
        - t09_rst.resources | length == 1
        - (t09_rst.resources[0].status.state | default('') | lower)
          in ['succeeded', 'ready', 'done', 'failed', 'error']
      retries: 160
      delay: 15

    - name: Require the PITR restore to have succeeded
      ansible.builtin.assert:
        that:
          - (t09_rst.resources[0].status.state | default('') | lower) in ['succeeded', 'ready', 'done']
        fail_msg: "PITR to {{ t09_target }} failed: {{ t09_rst.resources[0].status | default({}) }}"

    - name: Gate on cluster health after the PITR restore
      ansible.builtin.include_tasks: ../../test_common/tasks/health_gate.yml

    - name: Inspect the markers after recovery
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT CONCAT('GOOD_AFTER_RESTORE=', COUNT(*)) FROM {{ sysbench_database }}.pitr_markers WHERE label='good';
           SELECT CONCAT('BAD_AFTER_RESTORE=', COUNT(*)) FROM {{ sysbench_database }}.pitr_markers WHERE label='bad';
           SELECT CONCAT('TABLES_AFTER_RESTORE=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name LIKE 'sbtest%';" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t09_after
      changed_when: false
      retries: 20
      delay: 15
      until: t09_after.rc == 0

    - name: Require the good marker present and the bad marker rolled away
      ansible.builtin.assert:
        that:
          - "'GOOD_AFTER_RESTORE=1' in t09_after.stdout"
          - "'BAD_AFTER_RESTORE=0' in t09_after.stdout"
          - "'TABLES_AFTER_RESTORE=' ~ sysbench_tables in t09_after.stdout"
        fail_msg: >-
          PITR landed on the wrong point. target={{ t09_target }} result={{ t09_after.stdout }}
```

- `scenario_id: t09`, `scenario_title: Point-in-time recovery to a timestamp`.
- Evidence: `t09_markers.stdout_lines + ['PITR_TARGET=' ~ t09_target, 'RESTORE_STATE=' ~ state] + t09_after.stdout_lines`.

- [ ] **Step 5: Write the t10 role — recover to a GTID**

`ansible/roles/t10_pitr_gtid/tasks/main.yml`. Identical structure to t09 with a fresh base named `t10-base`, restore named `t10-restore`, and this instead of the marker/target block:

```yaml
    - name: Write good data, capture the GTID, then commit the destructive statement
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        POD="{{ t10_primary.stdout | trim }}"
        q() { kubectl -n "$NS" exec "$POD" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "$1" | tr -d '\r'; }
        q "CREATE TABLE IF NOT EXISTS {{ sysbench_database }}.gtid_markers
             (id INT AUTO_INCREMENT PRIMARY KEY, label VARCHAR(32))"
        q "DELETE FROM {{ sysbench_database }}.gtid_markers"
        q "INSERT INTO {{ sysbench_database }}.gtid_markers (label) VALUES ('keep-me')"
        echo "GTID_TARGET=$(q "SELECT @@GLOBAL.gtid_executed" | tr -d '\n')"
        echo "ROWS_BEFORE_DAMAGE=$(q "SELECT COUNT(*) FROM {{ sysbench_database }}.sbtest9")"
        sleep 20
        q "DELETE FROM {{ sysbench_database }}.sbtest9"
        q "INSERT INTO {{ sysbench_database }}.gtid_markers (label) VALUES ('after-damage')"
        echo "ROWS_AFTER_DAMAGE=$(q "SELECT COUNT(*) FROM {{ sysbench_database }}.sbtest9")"
      args:
        executable: /bin/bash
      register: t10_markers
      changed_when: true

    - name: Let the binlog server checkpoint the damage to MinIO
      ansible.builtin.pause:
        seconds: "{{ pitr_settle_seconds }}"

    - name: Extract the GTID target
      ansible.builtin.set_fact:
        t10_target: >-
          {{ (t10_markers.stdout_lines | select('match', '^GTID_TARGET=') | first).split('=', 1)[1] | trim }}
```

The restore body is t09's with:

```yaml
            pitr:
              type: gtid
              gtid: "{{ t10_target }}"
```

and the same `backupSource.binlogServer` block, `serverId: "{{ binlog_server_id | int + 11 }}"`.

Assertions after the restore:

```yaml
    - name: Require the deletion to be undone and the later marker absent
      ansible.builtin.assert:
        that:
          - (t10_after.stdout_lines | select('match', '^ROWS_AFTER_RESTORE=') | first).split('=')[1] | int
            == (t10_markers.stdout_lines | select('match', '^ROWS_BEFORE_DAMAGE=') | first).split('=')[1] | int
          - "'KEEP_MARKER=1' in t10_after.stdout"
          - "'DAMAGE_MARKER=0' in t10_after.stdout"
        fail_msg: >-
          GTID recovery landed wrong. target={{ t10_target }} result={{ t10_after.stdout }}
```

where `t10_after` selects `ROWS_AFTER_RESTORE` from `sbtest9`, `KEEP_MARKER` as the count of `label='keep-me'`, and `DAMAGE_MARKER` as the count of `label='after-damage'`.

- `scenario_id: t10`, `scenario_title: Point-in-time recovery to a GTID`.

Note for the implementer: `@@GLOBAL.gtid_executed` is a set like `f3c2…:1-4172`, and the operator recovers *through* that set. If the run shows the target is exclusive rather than inclusive, record which it is — that behaviour is exactly the kind of thing the documentation should state precisely, not hand-wave.

- [ ] **Step 6: Write the t11 role — an impossible target must fail**

`ansible/roles/t11_pitr_invalid_target/tasks/main.yml`, standard shape, body:

```yaml
    - name: Require a base backup to aim before
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t09-base
      register: t11_base
      failed_when: (t11_base.resources | default([]) | length) == 0

    - name: Remove any stale t11 restore object
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t11-restore
        wait: true
        wait_timeout: 180

    - name: Ask for recovery to a point long before the backup existed
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLRestore
          metadata:
            name: t11-restore
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            backupName: t09-base
            pitr:
              type: date
              date: "2001-01-01T00:00:00Z"
              backupSource:
                binlogServer:
                  image: "{{ binlog_server_image }}"
                  serverId: "{{ binlog_server_id | int + 12 }}"
                  storage:
                    s3:
                      bucket: "{{ binlog_bucket }}"
                      credentialsSecret: "{{ minio_credentials_secret }}"
                      endpointUrl: "http://minio.{{ mysql_namespace }}.svc.cluster.local:9000"
                      region: us-east-1
                      prefix: "{{ binlog_prefix }}"

    - name: Wait for the operator to reject or fail the impossible restore
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t11-restore
      register: t11_rst
      until:
        - t11_rst.resources | length == 1
        - (t11_rst.resources[0].status.state | default('') | lower) in ['failed', 'error']
      retries: 60
      delay: 15

    - name: Require a clean, explained failure
      ansible.builtin.assert:
        that:
          - (t11_rst.resources[0].status.state | default('') | lower) in ['failed', 'error']
          - (t11_rst.resources[0].status.stateDescription | default('') | length) > 0
        fail_msg: >-
          An impossible PITR target did not fail cleanly: {{ t11_rst.resources[0].status | default({}) }}

    - name: Delete the failed restore object so it cannot block later work
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t11-restore
        wait: true
        wait_timeout: 180

    - name: Gate on cluster health after the failed restore
      ansible.builtin.include_tasks: ../../test_common/tasks/health_gate.yml

    - name: Confirm the data is untouched
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "SELECT CONCAT('TABLES_AFTER_FAILED_RESTORE=', COUNT(*)) FROM information_schema.tables
             WHERE table_schema='{{ sysbench_database }}' AND table_name LIKE 'sbtest%';" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t11_after
      changed_when: false

    - name: Require the dataset to have survived
      ansible.builtin.assert:
        that:
          - "'TABLES_AFTER_FAILED_RESTORE=' ~ sysbench_tables in t11_after.stdout"
```

- `scenario_id: t11`, `scenario_title: An impossible recovery target fails cleanly`.
- Evidence: the restore `state`, its `stateDescription`, the health summary, and `t11_after.stdout_lines`.

If the operator instead *succeeds* and silently restores the plain backup, that is a genuine finding: record `status: failed` for the scenario, keep the evidence, and document the behaviour honestly in Task 10 rather than reshaping the assertion to match.

- [ ] **Step 7: Write the three playbooks**

`t09-pitr-timestamp.yml`, `t10-pitr-gtid.yml`, `t11-pitr-invalid-target.yml`, following Task 4 Step 5.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 9: Syntax-check**

Run: `cd ansible && for p in t09-pitr-timestamp t10-pitr-gtid t11-pitr-invalid-target; do ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/$p.yml; done`
Expected: no syntax errors.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Add PITR scenarios: timestamp, GTID, and an invalid target"
```

---

### Task 8: Scenario 12 — restore into a new cluster and let it replicate

The scenario that actually verifies the backup. Restore into a *separate* cluster from the MinIO objects alone, attach it as a replica of the live cluster, and prove it catches up and matches.

**Files:**
- Create: `ansible/roles/t12_restore_as_replica/tasks/main.yml`
- Create: `ansible/roles/t12_restore_as_replica/templates/verify-cluster.yaml.j2`
- Create: `ansible/playbooks/tests/t12-restore-as-replica.yml`
- Modify: `ansible/inventory/group_vars/all.yml`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: the shared includes.
- Produces: vars `verify_cluster_name: verify`, `verify_catchup_retries: 60`, `verify_catchup_delay: 10`. The scenario takes its own backup (`t12-base`) so it depends on no earlier scenario, and deletes the `verify` cluster and its copied secrets in an `always` block so the lab is left as found.

- [ ] **Step 1: Write the failing structural test**

Change `self.SCENARIOS[:11]` to `self.SCENARIOS` (all twelve) and add:

```python
    def test_restore_as_replica_is_a_real_verification(self) -> None:
        v = load_group_vars()
        self.assertEqual(v["verify_cluster_name"], "verify")
        self.assertNotEqual(v["verify_cluster_name"], v["mysql_cluster_name"])

        role = ANSIBLE / "roles" / "t12_restore_as_replica"
        text = (role / "tasks" / "main.yml").read_text()
        # restores from the object store, not from the source cluster's backup CR
        self.assertIn("backupSource", text)
        self.assertIn("destination", text)
        # copies both the user secret and the operator's internal secret
        self.assertIn("internal-", text)
        self.assertIn("secretsName", (role / "templates" / "verify-cluster.yaml.j2").read_text())
        # sets up replication and waits for catch-up
        self.assertIn("CHANGE REPLICATION SOURCE TO", text)
        self.assertIn("SOURCE_AUTO_POSITION", text)
        self.assertIn("Seconds_Behind_Source", text)
        self.assertIn("CHECKSUM TABLE", text)
        # cleans up after itself
        self.assertIn("always:", text)

    def test_verify_cluster_template_is_a_minimal_single_node(self) -> None:
        rendered = yaml.safe_load(
            render_template(
                ANSIBLE / "roles" / "t12_restore_as_replica" / "templates" / "verify-cluster.yaml.j2"
            )
        )
        spec = rendered["spec"]
        self.assertEqual(rendered["metadata"]["name"], "verify")
        self.assertEqual(int(spec["mysql"]["size"]), 1)
        self.assertFalse(spec["orchestrator"]["enabled"])
        self.assertFalse(spec["proxy"]["haproxy"]["enabled"])
        self.assertNotIn("pitr", spec["backup"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `KeyError: 'verify_cluster_name'`.

- [ ] **Step 3: Add the variables**

Append to `ansible/inventory/group_vars/all.yml`:

```yaml
verify_cluster_name: verify
verify_catchup_retries: 60
verify_catchup_delay: 10
```

- [ ] **Step 4: Write the verify cluster template**

`ansible/roles/t12_restore_as_replica/templates/verify-cluster.yaml.j2`:

```yaml
apiVersion: ps.percona.com/v1
kind: PerconaServerMySQL
metadata:
  name: {{ verify_cluster_name }}
  namespace: {{ mysql_namespace }}
  finalizers:
    - percona.com/delete-mysql-pods-in-order
spec:
  crVersion: "{{ ps_cr_version }}"
  secretsName: {{ verify_cluster_name }}-secrets
  updateStrategy: SmartUpdate
  upgradeOptions:
    apply: disabled
    versionServiceEndpoint: https://check.percona.com
  unsafeFlags:
    mysqlSize: true
    orchestratorSize: true
    proxySize: true
  mysql:
    clusterType: {{ mysql_cluster_type }}
    autoRecovery: true
    size: 1
    image: {{ mysql_image }}
    imagePullPolicy: IfNotPresent
    gracePeriod: 30
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        memory: 1024Mi
    affinity:
      antiAffinityTopologyKey: "none"
    volumeSpec:
      persistentVolumeClaim:
        resources:
          requests:
            storage: 5Gi
    configuration: |
      [mysqld]
      gtid_mode=ON
      enforce_gtid_consistency=ON
      log_bin=ON
      binlog_format=ROW
      binlog_expire_logs_seconds=86400
      innodb_buffer_pool_size=256M
      max_connections=80
      skip_name_resolve
  proxy:
    haproxy:
      enabled: false
      size: 1
      image: {{ haproxy_image }}
    router:
      enabled: false
      size: 1
      image: percona/percona-mysql-router:8.4.10
  orchestrator:
    enabled: false
    size: 1
    image: {{ orchestrator_image }}
  backup:
    enabled: true
    image: {{ xtrabackup_image }}
    imagePullPolicy: IfNotPresent
    storages:
      {{ backup_storage_name }}:
        type: s3
        verifyTLS: false
        s3:
          bucket: {{ backup_bucket }}
          credentialsSecret: {{ minio_credentials_secret }}
          endpointUrl: http://minio.{{ mysql_namespace }}.svc.cluster.local:9000
          region: us-east-1
          prefix: {{ verify_cluster_name }}
  toolkit:
    image: {{ toolkit_image }}
    imagePullPolicy: IfNotPresent
```

- [ ] **Step 5: Write the t12 role**

`ansible/roles/t12_restore_as_replica/tasks/main.yml`, standard shape. Body, in order:

```yaml
    - name: Take a dedicated backup for the verification restore
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t12-base
        wait: true
        wait_timeout: 180

    - name: Request the t12 base backup
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLBackup
          metadata:
            name: t12-base
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ mysql_cluster_name }}"
            storageName: "{{ backup_storage_name }}"
            type: full

    - name: Wait for the t12 base backup
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLBackup
        namespace: "{{ mysql_namespace }}"
        name: t12-base
      register: t12_base
      until:
        - t12_base.resources | length == 1
        - (t12_base.resources[0].status.state | default('') | lower)
          in ['succeeded', 'ready', 'done', 'failed', 'error']
      retries: 120
      delay: 10

    - name: Require the base backup and keep its destination
      ansible.builtin.assert:
        that:
          - (t12_base.resources[0].status.state | default('') | lower) in ['succeeded', 'ready', 'done']
          - (t12_base.resources[0].status.destination | default('') | length) > 0
        fail_msg: "t12 base backup failed: {{ t12_base.resources[0].status | default({}) }}"

    - name: Copy the lab secrets to the verification cluster's names
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        copy() {
          src="$1"; dst="$2"
          kubectl -n "$NS" get secret "$src" -o json \
            | python3 -c "import json,sys; d=json.load(sys.stdin); d['metadata']={'name':'$dst','namespace':'$NS'}; d.pop('status',None); print(json.dumps(d))" \
            | kubectl -n "$NS" apply -f -
        }
        copy {{ mysql_secrets_name }} {{ verify_cluster_name }}-secrets
        copy internal-{{ mysql_cluster_name }} internal-{{ verify_cluster_name }}
        if kubectl -n "$NS" get secret {{ mysql_cluster_name }}-ssl >/dev/null 2>&1; then
          copy {{ mysql_cluster_name }}-ssl {{ verify_cluster_name }}-ssl
        fi
        echo "SECRETS_COPIED={{ verify_cluster_name }}-secrets,internal-{{ verify_cluster_name }}"
      args:
        executable: /bin/bash
      register: t12_secrets
      changed_when: true
```

Why this step exists, and it belongs in the documentation as prominently as in the code: the restored datadir carries the *source* cluster's `mysql.user` table. If the new cluster is given freshly generated passwords, the operator will not be able to log in to the data it has just restored, and the cluster will sit in a crash loop that looks like a restore failure but is an authentication failure.

Then:

```yaml
    - name: Render the verification cluster
      ansible.builtin.template:
        src: verify-cluster.yaml.j2
        dest: "{{ repo_root }}/k8s/mysql/verify-cluster.yaml"
        mode: "0644"

    - name: Create the verification cluster
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        src: "{{ repo_root }}/k8s/mysql/verify-cluster.yaml"

    - name: Wait for the verification cluster to come up empty
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        kind: Pod
        namespace: "{{ mysql_namespace }}"
        label_selectors:
          - app.kubernetes.io/instance={{ verify_cluster_name }}
          - app.kubernetes.io/component=database
      register: t12_pods
      until:
        - t12_pods.resources | length >= 1
        - t12_pods.resources | rejectattr('status.phase', 'equalto', 'Running') | list | length == 0
      retries: 90
      delay: 10

    - name: Start a write workload on the live cluster
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ mysql_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e \
          "CREATE TABLE IF NOT EXISTS {{ sysbench_database }}.post_backup_writes
             (id INT AUTO_INCREMENT PRIMARY KEY, at DATETIME(6));
           INSERT INTO {{ sysbench_database }}.post_backup_writes (at)
             SELECT UTC_TIMESTAMP(6) FROM {{ sysbench_database }}.sbtest1 LIMIT 20000;
           SELECT CONCAT('WRITES_AFTER_BACKUP=', COUNT(*)) FROM {{ sysbench_database }}.post_backup_writes;" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t12_writes
      changed_when: true

    - name: Restore the backup into the verification cluster from MinIO
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: present
        definition:
          apiVersion: ps.percona.com/v1
          kind: PerconaServerMySQLRestore
          metadata:
            name: t12-restore
            namespace: "{{ mysql_namespace }}"
          spec:
            clusterName: "{{ verify_cluster_name }}"
            backupSource:
              destination: "{{ t12_base.resources[0].status.destination }}"
              storage:
                type: s3
                s3:
                  bucket: "{{ backup_bucket }}"
                  credentialsSecret: "{{ minio_credentials_secret }}"
                  endpointUrl: "http://minio.{{ mysql_namespace }}.svc.cluster.local:9000"
                  region: us-east-1

    - name: Wait for the cross-cluster restore
      kubernetes.core.k8s_info:
        kubeconfig: "{{ kubeconfig_path }}"
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQLRestore
        namespace: "{{ mysql_namespace }}"
        name: t12-restore
      register: t12_rst
      until:
        - t12_rst.resources | length == 1
        - (t12_rst.resources[0].status.state | default('') | lower)
          in ['succeeded', 'ready', 'done', 'failed', 'error']
      retries: 160
      delay: 15

    - name: Require the cross-cluster restore to have succeeded
      ansible.builtin.assert:
        that:
          - (t12_rst.resources[0].status.state | default('') | lower) in ['succeeded', 'ready', 'done']
        fail_msg: "Restore into {{ verify_cluster_name }} failed: {{ t12_rst.resources[0].status | default({}) }}"

    - name: Wait for the restored node to serve SQL
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} exec {{ verify_cluster_name }}-mysql-0 -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -N -e "SELECT 1" | tr -d '\r'
      args:
        executable: /bin/bash
      register: t12_ping
      changed_when: false
      retries: 40
      delay: 15
      until: t12_ping.rc == 0

    - name: Show what the restored copy knows before replication starts
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        V="{{ verify_cluster_name }}-mysql-0"
        q() { kubectl -n {{ mysql_namespace }} exec "$V" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "$1" | tr -d '\r'; }
        echo "RESTORED_GTID_PURGED=$(q 'SELECT @@GLOBAL.gtid_purged')"
        echo "RESTORED_TABLES=$(q "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{{ sysbench_database }}' AND table_name LIKE 'sbtest%'")"
        echo "RESTORED_POST_BACKUP_ROWS=$(q "SELECT IFNULL((SELECT COUNT(*) FROM {{ sysbench_database }}.post_backup_writes), 0)" 2>/dev/null || echo 0)"
      args:
        executable: /bin/bash
      register: t12_pre_repl
      changed_when: false

    - name: Point the restored copy at the live primary and start replicating
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        V="{{ verify_cluster_name }}-mysql-0"
        REPL_PASS=$(kubectl -n "$NS" get secret internal-{{ mysql_cluster_name }} -o jsonpath='{.data.replication}' | base64 -d)
        SOURCE_HOST="{{ mysql_cluster_name }}-mysql-0.{{ mysql_cluster_name }}-mysql.$NS.svc.cluster.local"
        kubectl -n "$NS" exec "$V" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -e \
          "STOP REPLICA;
           CHANGE REPLICATION SOURCE TO
             SOURCE_HOST='$SOURCE_HOST',
             SOURCE_PORT=3306,
             SOURCE_USER='replication',
             SOURCE_PASSWORD='$REPL_PASS',
             SOURCE_SSL=1,
             SOURCE_AUTO_POSITION=1;
           START REPLICA;"
        echo "SOURCE_HOST=$SOURCE_HOST"
      args:
        executable: /bin/bash
      register: t12_change_source
      changed_when: true

    - name: Wait for the restored copy to catch up
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        V="{{ verify_cluster_name }}-mysql-0"
        kubectl -n {{ mysql_namespace }} exec "$V" -c mysql -- \
          mysql -uroot -p{{ mysql_root_password }} -e "SHOW REPLICA STATUS\G" \
          | grep -E 'Replica_IO_Running|Replica_SQL_Running|Seconds_Behind_Source|Last_Error|Retrieved_Gtid_Set|Executed_Gtid_Set' \
          | sed 's/^ *//' | tr -d '\r'
      args:
        executable: /bin/bash
      register: t12_repl
      changed_when: false
      until:
        - t12_repl.stdout is search('Replica_IO_Running: Yes')
        - t12_repl.stdout is search('Replica_SQL_Running: Yes')
        - t12_repl.stdout is search('Seconds_Behind_Source: 0')
      retries: "{{ verify_catchup_retries }}"
      delay: "{{ verify_catchup_delay }}"

    - name: Compare both clusters once the writes have stopped
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        NS="{{ mysql_namespace }}"
        L="{{ mysql_cluster_name }}-mysql-0"
        V="{{ verify_cluster_name }}-mysql-0"
        ql() { kubectl -n "$NS" exec "$L" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "$1" | tr -d '\r'; }
        qv() { kubectl -n "$NS" exec "$V" -c mysql -- mysql -uroot -p{{ mysql_root_password }} -N -e "$1" | tr -d '\r'; }
        sleep 15
        echo "LIVE_POST_BACKUP_ROWS=$(ql "SELECT COUNT(*) FROM {{ sysbench_database }}.post_backup_writes")"
        echo "REPLICA_POST_BACKUP_ROWS=$(qv "SELECT COUNT(*) FROM {{ sysbench_database }}.post_backup_writes")"
        mismatch=0
        for i in $(seq 1 {{ sysbench_tables }}); do
          a=$(ql "CHECKSUM TABLE {{ sysbench_database }}.sbtest$i" | awk '{print $2}')
          b=$(qv "CHECKSUM TABLE {{ sysbench_database }}.sbtest$i" | awk '{print $2}')
          echo "CHECKSUM sbtest$i live=$a replica=$b"
          [ "$a" = "$b" ] || mismatch=$((mismatch+1))
        done
        echo "CHECKSUM_MISMATCHES=$mismatch"
        echo "LIVE_GTID=$(ql 'SELECT @@GLOBAL.gtid_executed')"
        echo "REPLICA_GTID=$(qv 'SELECT @@GLOBAL.gtid_executed')"
      args:
        executable: /bin/bash
      register: t12_compare
      changed_when: false

    - name: Require a caught-up, byte-identical replica
      ansible.builtin.assert:
        that:
          - "'CHECKSUM_MISMATCHES=0' in t12_compare.stdout"
          - (t12_compare.stdout_lines | select('match', '^REPLICA_POST_BACKUP_ROWS=') | first).split('=')[1] | int
            == (t12_compare.stdout_lines | select('match', '^LIVE_POST_BACKUP_ROWS=') | first).split('=')[1] | int
          - (t12_compare.stdout_lines | select('match', '^REPLICA_POST_BACKUP_ROWS=') | first).split('=')[1] | int > 0
        fail_msg: >-
          The restored copy is not a faithful replica: {{ t12_compare.stdout }}
```

- `scenario_id: t12`, `scenario_title: Restore into a new cluster, attach as a replica, catch up`.
- Evidence: `t12_secrets.stdout_lines + t12_writes.stdout_lines + ['RESTORE_STATE=' ~ state] + t12_pre_repl.stdout_lines + t12_change_source.stdout_lines + t12_repl.stdout_lines + t12_compare.stdout_lines`.

The `always` block:

```yaml
  always:
    - name: Delete the verification cluster
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: ps.percona.com/v1
        kind: PerconaServerMySQL
        namespace: "{{ mysql_namespace }}"
        name: "{{ verify_cluster_name }}"
        wait: true
        wait_timeout: 300

    - name: Delete the verification restore object and copied secrets
      kubernetes.core.k8s:
        kubeconfig: "{{ kubeconfig_path }}"
        state: absent
        api_version: "{{ item.api }}"
        kind: "{{ item.kind }}"
        namespace: "{{ mysql_namespace }}"
        name: "{{ item.name }}"
      loop:
        - {api: "ps.percona.com/v1", kind: "PerconaServerMySQLRestore", name: "t12-restore"}
        - {api: "v1", kind: "Secret", name: "{{ verify_cluster_name }}-secrets"}
        - {api: "v1", kind: "Secret", name: "internal-{{ verify_cluster_name }}"}
        - {api: "v1", kind: "Secret", name: "{{ verify_cluster_name }}-ssl"}
      failed_when: false

    - name: Delete the verification cluster's PVCs
      ansible.builtin.shell: |
        set -euo pipefail
        export KUBECONFIG="{{ kubeconfig_path }}"
        kubectl -n {{ mysql_namespace }} delete pvc \
          -l app.kubernetes.io/instance={{ verify_cluster_name }} --ignore-not-found
      args:
        executable: /bin/bash
      changed_when: true
      failed_when: false
```

- [ ] **Step 6: Write the t12 playbook**

`ansible/playbooks/tests/t12-restore-as-replica.yml`, following Task 4 Step 5, with role `t12_restore_as_replica`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 8: Syntax-check the whole suite**

Run: `cd ansible && ../.venv/bin/ansible-playbook --syntax-check playbooks/tests/all.yml`
Expected: no syntax errors — every role referenced by `all.yml` now exists.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Add the restore-as-replica verification scenario"
```

---

### Task 9: Deploy the lab and run the suite for real

Nothing before this point has touched a live cluster. This task produces the measured results the documentation is built from.

**Files:**
- Modify: whatever the run proves wrong (roles, timeouts, assertions)
- Create: `docs/results/<run_id>.jsonl`, `docs/results/<run_id>-run.md`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: a completed run report at `docs/results/<run_id>-run.md`, and the `run_id` value that Task 10 quotes.

- [ ] **Step 1: Tear down the stale cluster**

The kind cluster from the earlier replication lab is still running and in CrashLoopBackOff; it must not be reused.

Run: `make teardown`
Expected: `kind delete cluster --name mysql-lab` succeeds and `.kube/config` is removed.

- [ ] **Step 2: Deploy fresh**

Run: `make deploy`
Expected: PLAY RECAP with `failed=0`. Then confirm PITR actually came up:

```bash
export KUBECONFIG="$PWD/.kube/config"
kubectl -n mysql get pods
kubectl -n mysql get ps lab -o jsonpath='{.spec.backup.pitr}{"\n"}'
```
Expected: a binlog-server pod Running alongside the two MySQL pods, HAProxy and Orchestrator.

If the binlog server does not appear, check the operator log (`kubectl -n mysql logs deploy/ps-operator | tail -50`) before going further — the PITR scenarios cannot pass without it.

- [ ] **Step 3: Load the dataset**

Run: `make load-data && make verify`
Expected: 10 sysbench tables, size between `data_size_min_mb` and `data_size_max_mb`, replica IO and SQL both ON.

- [ ] **Step 4: Confirm binlogs are reaching MinIO before testing recovery**

```bash
kubectl -n mysql run mc-check --rm -i --restart=Never --quiet --image=minio/mc:RELEASE.2024-11-21T17-21-54Z --command -- \
  sh -c 'mc alias set local http://minio:9000 minio minio12345 >/dev/null; mc ls --recursive local/mysql-lab-binlogs | tail'
```
Expected: at least one object. An empty binlog bucket means PITR is not actually streaming; fix that before running the suite.

- [ ] **Step 5: Run the full suite**

Run: `make test-backups 2>&1 | tee /tmp/suite-run.log`
Expected: twelve scenarios recorded, a report at `docs/results/<run_id>-run.md`.

Note the `run_id` printed at the start — Task 10 references it.

- [ ] **Step 6: Fix what the run proves wrong, one scenario at a time**

For each failing scenario: read its evidence in the report, then investigate the actual cluster state (`kubectl -n mysql get ps,pods`, `kubectl -n mysql describe psrestore <name>`, `kubectl -n mysql logs job/<xb-...>`, the operator log). Fix the role, re-run just that scenario with `make test-tNN RUN_ID=<same run_id>`, and confirm.

Rules for this step:

- Fix the code or fix the expectation, never the evidence. If the operator's real behaviour differs from what the assertion expected, change the assertion **and** note the discovery — it is documentation material.
- If a scenario cannot be made to pass, leave it recorded as failed with its evidence intact and document why in Task 10. A suite that honestly reports 11/12 is worth more than one that was reshaped until it went green.
- Likely trouble spots, based on the CRD review: the `status.destination` string format used by the t03 prefix regex; whether the operator prunes on `keep` within the t06 pause; whether an out-of-range PITR target fails or silently degrades in t11; and, most of all, the secret copying and cross-cluster restore in t12.

- [ ] **Step 7: Re-run the whole suite end to end once it is green**

Run: `make test-backups 2>&1 | tee /tmp/suite-final.log`
Expected: a single clean `run_id` whose report covers all twelve scenarios in one pass. This is the run the blog post quotes — a report stitched together from a dozen partial re-runs is not a result.

- [ ] **Step 8: Commit the run**

```bash
git add -A
git commit -m "Record a full backup, restore and PITR suite run"
```

---

### Task 10: Documentation

Rewrite the lab's documentation around backup verification, using only numbers from the Task 9 run.

**Files:**
- Rewrite: `README.md`, `docs/blog-draft.md`, `docs/diagrams/architecture.mmd`
- Create: `docs/backup-architecture.md`, `docs/test-catalogue.md`
- Delete: `docs/how-it-works.md` (replaced by `docs/backup-architecture.md`)
- Modify: `docs/diagrams/README.md`
- Test: `tests/test_lab_config.py`

**Interfaces:**
- Consumes: `docs/results/<run_id>-run.md` from Task 9.
- Produces: the finished lab documentation.

- [ ] **Step 1: Write the failing documentation test**

Replace the removed `test_docs_describe_force_delete_failover_not_sigstop` with:

```python
    def test_docs_are_about_backup_verification(self) -> None:
        readme = (ROOT / "README.md").read_text()
        arch = (ROOT / "docs" / "backup-architecture.md").read_text()
        catalogue = (ROOT / "docs" / "test-catalogue.md").read_text()
        blog = (ROOT / "docs" / "blog-draft.md").read_text()

        self.assertFalse((ROOT / "docs" / "how-it-works.md").exists())
        self.assertIn("20260911-mysql-replication-backups", readme)
        self.assertNotIn("20260910-mysql-replication-setup/", readme)

        for doc in (readme, arch, catalogue, blog):
            self.assertIn("PITR", doc + doc.upper())

        # every scenario is documented, and the catalogue says how to run each one
        for sid, _ in self.SCENARIOS:
            self.assertIn(sid, catalogue, f"{sid} missing from the catalogue")
            self.assertIn(f"make test-{sid}", catalogue)

        # the thesis has to be stated, not implied
        for doc in (readme, blog):
            self.assertIn("replica", doc.lower())
        self.assertIn("binlog server", arch.lower())
        self.assertIn("internal-", arch)

        # results are real and referenced
        results = sorted((ROOT / "docs" / "results").glob("*-run.md"))
        self.assertTrue(results, "no measured run report in docs/results/")
        self.assertIn(results[-1].name, blog + catalogue + readme)

    def test_docs_have_no_placeholders(self) -> None:
        for name in ("README.md", "docs/backup-architecture.md",
                     "docs/test-catalogue.md", "docs/blog-draft.md"):
            text = (ROOT / name).read_text()
            for bad in ("TODO", "TBD", "XXX", "<fill", "PLACEHOLDER", "Lorem"):
                self.assertNotIn(bad, text, f"{name} still contains {bad}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test`
Expected: FAIL — `docs/backup-architecture.md` does not exist.

- [ ] **Step 3: Write `docs/backup-architecture.md`**

Sections, in order:

1. **What the operator actually does when you ask for a backup** — the `PerconaServerMySQLBackup` object, the `xb-*` job it spawns, XtraBackup streaming to S3, and where `status.destination` points. Quote the real destination string from the run.
2. **The binlog server** — what `backup.pitr.binlogServer` deploys, that it registers as a replica (`serverId`) and streams binary logs to `mysql-lab-binlogs`, the meaning of `checkpointInterval` and `checkpointSize`, and why a PITR window is bounded by the oldest full backup and the streamed binlogs, not by the binlogs alone.
3. **Restore in place** — that the operator stops the cluster, restores the datadir, and rebuilds replicas; the downtime this implies.
4. **Point-in-time recovery** — `pitr.type: date` versus `gtid`, the exact date format, and what the run showed about inclusivity of the GTID target.
5. **Restore into a different cluster** — `backupSource.destination`, and the secret-copying requirement, with the failure mode spelled out: the restored datadir carries the source cluster's `mysql.user` table, so a new cluster with fresh credentials cannot authenticate against its own restored data.
6. **Why replication is the real test** — `gtid_purged` is restored by XtraBackup, which is what makes `SOURCE_AUTO_POSITION=1` work with no coordinates; a replica that reaches `Seconds_Behind_Source: 0` and matches on `CHECKSUM TABLE` has proved the backup was consistent, complete and usable in a way no green job status can.

Three mermaid diagrams in `docs/diagrams/architecture.mmd` and embedded here: the backup path, the PITR restore path, and the restore-as-replica path. Update `docs/diagrams/README.md` to describe the new diagrams.

- [ ] **Step 4: Write `docs/test-catalogue.md`**

A section per scenario, in order t01–t12, each with: what it proves, how it does it, what it asserts, the measured duration from the run, and its `make test-tNN` command. Open with a table mapping the three groups — produced (01–06), restores in place (07–11), verified (12) — and state plainly that only the last group is verification.

- [ ] **Step 5: Rewrite `README.md`**

Structure: what the lab is and the one claim it makes; the component table (kind, operator 1.2.0, Percona Server 8.4, XtraBackup, binlog server, MinIO, Prometheus/Grafana); prerequisites; quick start (`bootstrap`, `deploy`, `load-data`, `verify`, `test-backups`); the twelve scenarios as a short table linking to the catalogue; service endpoints; where results land; lab-only credentials. Fix every path reference to `20260911-mysql-replication-backups/`.

- [ ] **Step 6: Rewrite `docs/blog-draft.md`**

The narrative, built from the measured run:

- Hook: a green backup schedule is not a backup strategy. Most teams learn this during an incident.
- What the lab is, in one paragraph, with the component list.
- The three groups of scenarios, with the measured results table lifted from the run report.
- The two findings that carry the post: what PITR to a timestamp and to a GTID actually did, and what happened when the backup was restored into a fresh cluster and told to replicate — including the secret-copying trap and the catch-up numbers.
- Anything that failed or surprised, stated plainly.
- Closing: the checklist a reader should take away — restore on a schedule, restore somewhere else, attach it as a replica, compare checksums.

Quote the run report by name so a reader can find the raw evidence.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `make test`
Expected: PASS.

- [ ] **Step 8: Read the documentation once more against the run report**

Open `docs/results/<run_id>-run.md` beside each document and check every number, duration, table count and quoted line appears in the report. Any number that does not is either wrong or unverified — remove it or go measure it.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Document the backup verification lab and its measured results"
```

---

## Notes for the executor

- Run everything from `20260911-mysql-replication-backups/`. The Ansible playbooks derive `repo_root` from `playbook_dir`; test playbooks live one level deeper than the existing ones, so their `kubeconfig_path` uses `../../..` where the existing playbooks use `../..`.
- `make test` is the offline structural suite and must stay fast. It never touches Kubernetes.
- Tasks 1–8 are pure authoring and can be completed without a cluster. Task 9 is the first time anything runs for real, and it is where the plan expects to be corrected by reality.
- When reality and the plan disagree, reality wins and the documentation records what reality said.
