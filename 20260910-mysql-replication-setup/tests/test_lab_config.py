"""Structural tests for the shipped MySQL lab (templates + inventory).

These tests drive the Ansible group_vars and Jinja templates that deploy
renders. They fail if replication, sysbench sizing, backups, failover, or
Prometheus scrape config disappear from the installer source of truth.
"""

from __future__ import annotations

import pathlib
import re
import unittest

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"
TEMPLATES_CLUSTER = ANSIBLE / "roles" / "mysql_cluster" / "templates"
TEMPLATES_MONITORING = ANSIBLE / "roles" / "monitoring" / "templates"
PLAYBOOKS = ANSIBLE / "playbooks"
REPO_README = ROOT.parent / "README.md"


def _strip_jinja(text: str) -> str:
    return re.sub(r"\{\{.*?\}\}", "PLACEHOLDER", text, flags=re.S)


def load_group_vars() -> dict:
    raw = (ANSIBLE / "inventory" / "group_vars" / "all.yml").read_text()
    data = yaml.safe_load(_strip_jinja(raw))
    assert isinstance(data, dict)
    return data


def render_template(path: pathlib.Path, extra: dict | None = None) -> str:
    vars_ = load_group_vars()
    vars_.update(
        {
            "repo_root": str(ROOT),
            "kubeconfig_path": str(ROOT / ".kube" / "config"),
            "playbook_dir": str(PLAYBOOKS),
        }
    )
    if extra:
        vars_.update(extra)
    env = Environment(
        loader=FileSystemLoader(str(path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    return env.get_template(path.name).render(**vars_)


class LabConfigTests(unittest.TestCase):
    def test_group_vars_define_async_source_replica_topology(self) -> None:
        v = load_group_vars()
        self.assertEqual(v["mysql_cluster_type"], "async")
        self.assertGreaterEqual(int(v["mysql_size"]), 2)
        self.assertGreater(int(v["mysql_scale_out_size"]), int(v["mysql_size"]))
        self.assertTrue(v["orchestrator_enabled"])
        self.assertNotIn("galera", str(v).lower())
        self.assertNotIn("wsrep", str(v).lower())
        self.assertNotEqual(v["kind_cluster_name"], "clickhouse-lab")

    def test_sysbench_is_ten_tables_around_500mb(self) -> None:
        v = load_group_vars()
        self.assertEqual(int(v["sysbench_tables"]), 10)
        self.assertGreaterEqual(int(v["data_size_min_mb"]), 400)
        self.assertLessEqual(int(v["data_size_max_mb"]), 700)
        self.assertGreaterEqual(int(v["data_size_max_mb"]), int(v["data_size_min_mb"]))
        self.assertGreater(int(v["sysbench_table_size"]), 0)
        self.assertEqual(v["sysbench_database"], "sbtest")
        load = (ANSIBLE / "roles" / "load_sysbench" / "tasks" / "main.yml").read_text()
        self.assertIn("apt-get install", load)
        self.assertIn("sysbench oltp_read_write", load)

    def test_user_secret_only_lists_operator_known_users(self) -> None:
        rendered = render_template(TEMPLATES_CLUSTER / "secrets.yaml.j2")
        secret = yaml.safe_load(rendered)
        keys = set(secret["stringData"].keys())
        allowed = {
            "root",
            "xtrabackup",
            "monitor",
            "operator",
            "replication",
            "orchestrator",
            "heartbeat",
        }
        self.assertEqual(keys, allowed)
        self.assertNotIn("admin", keys)
        self.assertNotIn("clustercheck", keys)

    def test_cluster_template_enables_orchestrator_backups_and_gtid(self) -> None:
        rendered = render_template(TEMPLATES_CLUSTER / "cluster.yaml.j2")
        spec = yaml.safe_load(rendered)
        mysql = spec["spec"]["mysql"]
        self.assertEqual(mysql["clusterType"], "async")
        self.assertGreaterEqual(int(mysql["size"]), 2)
        self.assertTrue(spec["spec"]["orchestrator"]["enabled"])
        self.assertTrue(spec["spec"]["backup"]["enabled"])
        self.assertGreaterEqual(len(spec["spec"]["backup"]["schedule"]), 1)
        storages = spec["spec"]["backup"]["storages"]
        self.assertIn("minio", storages)
        config = mysql.get("configuration", "")
        self.assertIn("gtid_mode=ON", config)
        self.assertIn("enforce_gtid_consistency=ON", config)
        sidecar_env = mysql["sidecars"][0]["env"]
        self.assertTrue(
            any(e.get("name") == "MYSQLD_EXPORTER_PASSWORD" for e in sidecar_env),
            "mysqld_exporter v0.16 needs MYSQLD_EXPORTER_PASSWORD, not DATA_SOURCE_NAME",
        )

    def test_nodeport_selectors_match_operator_labels(self) -> None:
        docs = list(
            yaml.safe_load_all(
                render_template(TEMPLATES_CLUSTER / "nodeports.yaml.j2")
            )
        )
        by_name = {d["metadata"]["name"]: d for d in docs}
        self.assertEqual(
            by_name["mysql-primary-nodeport"]["spec"]["selector"][
                "app.kubernetes.io/component"
            ],
            "proxy",
        )
        self.assertEqual(
            by_name["mysql-metrics"]["spec"]["selector"]["app.kubernetes.io/component"],
            "database",
        )

    def test_monitoring_scrapes_mysql_and_ships_grafana_dashboard(self) -> None:
        monitors = yaml.safe_load_all(
            render_template(TEMPLATES_MONITORING / "servicemonitors.yaml.j2")
        )
        docs = list(monitors)
        sm = next(d for d in docs if d.get("kind") == "ServiceMonitor")
        self.assertIn("mysql", sm["metadata"]["name"])
        relabel = sm["spec"]["endpoints"][0]["relabelings"]
        self.assertTrue(
            any(r.get("targetLabel") == "job" and r.get("replacement") == "mysql" for r in relabel),
            "ServiceMonitor must relabel job=mysql for verify/Grafana",
        )
        dash = render_template(TEMPLATES_MONITORING / "grafana-dashboard.yaml.j2")
        self.assertIn("mysql-lab", dash)
        self.assertIn("mysqld", dash.lower() + dash)

    def test_ops_playbooks_exist_and_target_live_cluster(self) -> None:
        for name in (
            "site.yml",
            "load-data.yml",
            "verify.yml",
            "teardown.yml",
            "failover.yml",
            "backup.yml",
            "restore.yml",
            "scale-out.yml",
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

    def test_lab_entrypoints_and_repo_index(self) -> None:
        makefile = (ROOT / "Makefile").read_text()
        for target in (
            "deploy",
            "load-data",
            "verify",
            "failover",
            "backup",
            "restore",
            "scale-out",
        ):
            self.assertIn(target, makefile)
        lab_sh = (ROOT / "scripts" / "lab.sh").read_text()
        self.assertIn("failover", lab_sh)
        self.assertIn("scale-out", lab_sh)
        index = REPO_README.read_text()
        self.assertIn("20260910-mysql-replication-setup", index)

    def test_failover_role_requires_replica_rejoin_after_force_delete(self) -> None:
        text = (ANSIBLE / "roles" / "failover_test" / "tasks" / "main.yml").read_text()
        self.assertIn("--grace-period=0", text)
        self.assertIn("/api/recover/", text)
        self.assertNotIn("SIGSTOP", text)
        self.assertIn("OLD_READ_ONLY", text)
        self.assertIn("OLD_REPLICA_IO", text)
        self.assertIn("OLD_SOURCE_HOST", text)
        self.assertIn("REJOIN_OK", text)
        # The rejoin wait must fail the play if the former source does not follow.
        self.assertNotRegex(
            text,
            r"Wait for the former source pod to be recreated[\s\S]*failed_when:\s*false",
        )

    def test_docs_describe_force_delete_failover_not_sigstop(self) -> None:
        readme = (ROOT / "README.md").read_text()
        how = (ROOT / "docs" / "how-it-works.md").read_text()
        self.assertIn("force-delete", readme.lower() + how.lower())
        self.assertNotIn("SIGSTOP", readme)
        self.assertNotIn("SIGSTOP", how)


if __name__ == "__main__":
    unittest.main()
