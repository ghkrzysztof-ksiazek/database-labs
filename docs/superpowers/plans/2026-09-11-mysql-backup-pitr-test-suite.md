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
