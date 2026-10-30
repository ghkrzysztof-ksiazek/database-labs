"""The lab procedure in the manual is the same procedure as scripts/deploy.sh."""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def manual_bash() -> str:
    text = (ROOT / "docs" / "manual-setup.md").read_text()
    return "\n".join(re.findall(r"```bash\n(.*?)```", text, flags=re.S))


class LabLayoutTests(unittest.TestCase):
    def test_repo_index_lists_this_lab(self) -> None:
        readme = REPO / "README.md"
        if not readme.is_file():
            self.skipTest("repository index not present")
        self.assertIn("20261029-clickhouse-replicated-ha", readme.read_text())

    def test_compose_services_and_ports(self) -> None:
        compose = (ROOT / "docker" / "docker-compose.yml").read_text()
        for service in ("keeper-1", "keeper-2", "keeper-3", "ch-1", "ch-2", "haproxy"):
            self.assertIn(f"container_name: {service}", compose)
        self.assertIn("clickhouse/clickhouse-server:25.8", compose)
        self.assertIn("clickhouse/clickhouse-keeper:25.8", compose)
        self.assertIn("haproxy:3.2", compose)
        for port in ("127.0.0.1:19000:9000", "127.0.0.1:18123:8123", "127.0.0.1:18404:8404"):
            self.assertIn(port, compose)
        self.assertNotIn("restart:", compose)

    def test_manual_contains_the_deploy_statements(self) -> None:
        deploy = (ROOT / "scripts" / "deploy.sh").read_text()
        manual = manual_bash()
        for snippet in (
            "iptables-legacy -P FORWARD ACCEPT",
            "schema.sql",
            "FROM numbers(1000000)",
            "--name loadgen --network ch-ha",
        ):
            self.assertIn(snippet, deploy, snippet)
            self.assertIn(snippet, manual, snippet)

    def test_haproxy_checks_replicas_status(self) -> None:
        cfg = (ROOT / "docker" / "haproxy" / "haproxy.cfg").read_text()
        self.assertEqual(cfg.count("option httpchk GET /replicas_status"), 2)
        self.assertIn("check port 8123", cfg)
        self.assertIn("on-marked-down shutdown-sessions", cfg)

    def test_table_is_replicated_on_the_cluster(self) -> None:
        schema = (ROOT / "docker" / "clickhouse" / "schema.sql").read_text()
        self.assertIn("ON CLUSTER lab", schema)
        self.assertIn("ReplicatedMergeTree('/clickhouse/tables/{shard}/lab/events', '{replica}')", schema)

    def test_writeup_teaches_the_ideas_before_the_experiments(self) -> None:
        readme = (ROOT / "README.md").read_text()
        for heading in (
            "What you will build", "What you will learn", "Before you start",
            "Ideas you need first", "When something goes wrong",
            "What is different in production", "Glossary", "Clean up",
        ):
            self.assertIn(heading, readme, heading)
        self.assertLess(readme.index("Ideas you need first"), readme.index("Experiment A"))
        manual = (ROOT / "docs" / "manual-setup.md").read_text()
        self.assertIn("What you should see", manual)
        self.assertIn("How to check", manual)


if __name__ == "__main__":
    unittest.main()
