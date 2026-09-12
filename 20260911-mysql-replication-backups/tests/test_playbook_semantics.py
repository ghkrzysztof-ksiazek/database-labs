"""Regression checks for failures that valid YAML and syntax checks can miss."""

from __future__ import annotations

import pathlib
import re
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"
CONDITIONALS = {"when", "until", "failed_when", "changed_when"}
SCENARIOS = (
    "t01_backup_full", "t02_backup_from_replica", "t03_backup_incremental",
    "t04_storage_contents", "t05_backup_scheduled", "t06_backup_retention",
    "t07_restore_in_place", "t08_restore_dropped_table", "t09_pitr_timestamp",
    "t10_pitr_gtid", "t11_pitr_invalid_target", "t12_restore_as_replica",
)


def load(path):
    return yaml.safe_load(path.read_text())


def tasks_in(tasks):
    """Visit nested task blocks in execution order, including failure handlers."""
    for task in tasks:
        yield task
        for branch in ("block", "rescue", "always"):
            yield from tasks_in(task.get(branch, []))


def invalid_conditionals(node, location="root"):
    """A condition may be scalar or a flat list of scalar expressions."""
    errors = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{location}.{key}"
            if key in CONDITIONALS:
                expressions = value if isinstance(value, list) else [value]
                for index, expression in enumerate(expressions):
                    if isinstance(expression, (dict, list)):
                        errors.append(f"{child}[{index}]: {expression!r}")
            errors.extend(invalid_conditionals(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            errors.extend(invalid_conditionals(value, f"{location}[{index}]"))
    return errors


class PlaybookSemanticsTests(unittest.TestCase):
    def test_detector_rejects_colon_space_mapping_and_nested_lists(self):
        broken = yaml.safe_load("until:\n  - result.stdout is search('Replica_IO_Running: Yes')")
        self.assertEqual(len(invalid_conditionals(broken)), 1)
        self.assertEqual(len(invalid_conditionals({"when": [["ready"]]})), 1)
        valid = yaml.safe_load('until:\n  - "result.stdout is search(\'Replica_IO_Running: Yes\')"')
        self.assertEqual(invalid_conditionals(valid), [])
        self.assertEqual(invalid_conditionals({"changed_when": False}), [])

    def test_all_task_conditionals_are_scalar_expressions(self):
        paths = sorted((ANSIBLE / "roles").glob("*/tasks/**/*.yml"))
        paths += sorted((ANSIBLE / "playbooks").rglob("*.yml"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(invalid_conditionals(load(path)), [])

    def test_ordered_suite_runs_all_twelve_and_always_reports(self):
        play = load(ANSIBLE / "playbooks/tests/all.yml")[0]
        blocks = [task for task in play["tasks"] if "block" in task]
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        roles = [task["ansible.builtin.include_role"]["name"] for task in block["block"]]
        self.assertEqual(roles, list(SCENARIOS))
        reports = [task.get("ansible.builtin.include_role", {}).get("name")
                   for task in tasks_in(block.get("always", []))]
        self.assertIn("test_report", reports)
        for role in SCENARIOS:
            sid, slug = role.split("_", 1)
            path = ANSIBLE / "playbooks/tests" / f"{sid}-{slug.replace('_', '-')}.yml"
            with self.subTest(role=role):
                self.assertIn(role, load(path)[0]["roles"])

    def test_t12_records_cleanup_failures_and_only_passes_after_cleanup(self):
        role = load(ANSIBLE / "roles/t12_restore_as_replica/tasks/main.yml")
        outer = next(task for task in role if "block" in task)
        inner = outer["block"][0]
        self.assertIn("block", inner)
        cleanup = list(tasks_in(inner["always"]))
        self.assertTrue(any(task.get("kubernetes.core.k8s", {}).get("state") == "absent"
                            for task in cleanup))
        self.assertTrue(any(task.get("ansible.builtin.include_role", {}).get("tasks_from")
                            == "health_gate.yml" for task in cleanup))
        # Failures from inner always must reach an enclosing handler, not a
        # sibling rescue (Ansible does not send always failures to that rescue).
        failure_records = [task for task in tasks_in(outer["rescue"])
                           if task.get("ansible.builtin.include_role", {}).get("tasks_from")
                           == "record_result.yml"]
        self.assertEqual(len(failure_records), 1)
        self.assertEqual(failure_records[0]["vars"]["scenario_id"], "t12")
        self.assertEqual(failure_records[0]["vars"]["scenario_status"], "failed")
        self.assertTrue(any("ansible.builtin.fail" in task for task in outer["rescue"]))
        self.assertFalse(any(task.get("vars", {}).get("scenario_status") == "passed"
                             for task in tasks_in([inner])))
        passed = outer["block"][1:]
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0]["vars"]["scenario_status"], "passed")

    def test_pitr_markers_identify_this_attempt_and_are_written_after_the_base(self):
        cases = (
            ("t09_pitr_timestamp", "pitr_markers", {"GOOD_AFTER_RESTORE": "good-{{ t_start }}",
                                                   "BAD_AFTER_RESTORE": "bad-{{ t_start }}"}),
            ("t10_pitr_gtid", "gtid_markers", {"KEEP_MARKER": "keep-me-{{ t_start }}",
                                               "DAMAGE_MARKER": "after-damage-{{ t_start }}"}),
        )
        for role, table, expected in cases:
            with self.subTest(role=role):
                sid = role.split("_", 1)[0]
                tasks = list(tasks_in(load(ANSIBLE / "roles" / role / "tasks/main.yml")))
                base = next(i for i, task in enumerate(tasks)
                            if task.get("kubernetes.core.k8s", {}).get("definition", {}).get("kind")
                            == "PerconaServerMySQLBackup")
                waited = next(i for i, task in enumerate(tasks) if task.get("register") == sid + "_base")
                restore = next(i for i, task in enumerate(tasks)
                               if task.get("kubernetes.core.k8s", {}).get("definition", {}).get("kind")
                               == "PerconaServerMySQLRestore")
                writes = [(i, task["ansible.builtin.shell"]) for i, task in enumerate(tasks)
                          if "INSERT INTO" in task.get("ansible.builtin.shell", "")
                          and table in task["ansible.builtin.shell"]]
                self.assertEqual(len(writes), 1)
                write_index, write_sql = writes[0]
                self.assertLess(base, waited)
                self.assertLess(waited, write_index)
                self.assertLess(write_index, restore)
                # No setup step may put this attempt marker into the base.
                for task in tasks[:base]:
                    self.assertNotIn(table, task.get("ansible.builtin.shell", ""))
                inserted = re.findall(r"INSERT INTO [^\n]+?VALUES \('([^']+)'", write_sql)
                self.assertEqual(set(inserted), set(expected.values()))
                after_index = next(i for i, task in enumerate(tasks) if task.get("register") == sid + "_after")
                self.assertLess(restore, after_index)
                after_sql = tasks[after_index]["ansible.builtin.shell"]
                counted = dict(re.findall(
                    r"SELECT CONCAT\('([^']+)=', COUNT\(\*\)\).*?WHERE label='([^']+)'", after_sql))
                self.assertEqual(counted, expected)
                assertions = [condition for task in tasks[after_index + 1:]
                              for condition in task.get("ansible.builtin.assert", {}).get("that", [])]
                retained, excluded = expected
                self.assertTrue(any(retained + "=1" in str(condition) for condition in assertions))
                self.assertTrue(any(excluded + "=0" in str(condition) for condition in assertions))

    def test_pitr_switches_archive_before_creating_each_new_base(self):
        for role in ("t09_pitr_timestamp", "t10_pitr_gtid"):
            tasks = list(tasks_in(load(ANSIBLE / "roles" / role / "tasks/main.yml")))
            timeline = [i for i, task in enumerate(tasks)
                        if task.get("ansible.builtin.include_role", {}).get("tasks_from") == "pitr_timeline.yml"]
            backups = [i for i, task in enumerate(tasks)
                       if task.get("kubernetes.core.k8s", {}).get("definition", {}).get("kind")
                       == "PerconaServerMySQLBackup"]
            with self.subTest(role=role):
                self.assertEqual(len(timeline), 1)
                self.assertTrue(backups)
                self.assertLess(timeline[0], min(backups))
                restores = [task["kubernetes.core.k8s"]["definition"] for task in tasks
                            if task.get("kubernetes.core.k8s", {}).get("definition", {}).get("kind")
                            == "PerconaServerMySQLRestore"]
                self.assertTrue(restores)
                for restore in restores:
                    prefix = restore["spec"]["pitr"]["backupSource"]["binlogServer"]["storage"]["s3"]["prefix"]
                    self.assertEqual(prefix, "{{ recovery_binlog_prefix }}")

    def test_gtid_capture_handles_multiple_uuid_lines_without_escaped_newlines(self):
        fixture = "11111111-1111-1111-1111-111111111111:1-10,\n22222222-2222-2222-2222-222222222222:1-20"
        expected = fixture.replace("\n", "")
        for role in ("t10_pitr_gtid", "t12_restore_as_replica"):
            tasks = tasks_in(load(ANSIBLE / "roles" / role / "tasks/main.yml"))
            helpers_tested = 0
            for task in tasks:
                script = task.get("ansible.builtin.shell", "")
                if not isinstance(script, str):
                    continue
                for line in script.splitlines():
                    match = re.match(r"\s*(q|ql|qv)\(\) \{.*\}$", line)
                    if not match:
                        continue
                    with self.subTest(role=role, task=task.get("name"), helper=match[1]):
                        self.assertIn("--raw", line)
                        function = re.sub(r"\{\{.*?\}\}", "fixture", line)
                        invocation = f"{match[1]} 'SELECT @@GLOBAL.gtid_executed'"
                        if role == "t10_pitr_gtid":
                            target = next(item for item in script.splitlines() if 'echo "GTID_TARGET=' in item)
                            invocation = target
                        command = "kubectl() { printf '%s\\n' \"$GTID_FIXTURE\"; }\n" + function + "\n" + invocation
                        result = subprocess.run(["/bin/bash", "-c", command],
                                                env={"GTID_FIXTURE": fixture, "PATH": "/usr/bin:/bin"},
                                                capture_output=True, text=True, check=True)
                        actual = result.stdout.removeprefix("GTID_TARGET=").rstrip("\n")
                        self.assertEqual(actual, expected)
                        helpers_tested += 1
            self.assertGreater(helpers_tested, 0)


if __name__ == "__main__":
    unittest.main()
