"""The lab procedure in the manual is the same procedure as scripts/deploy.sh."""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def manual_bash() -> str:
    text = (ROOT / "docs" / "manual-setup.md").read_text()
    blocks = re.findall(r"```bash\n(.*?)```", text, flags=re.S)
    return "\n".join(blocks)


class LabLayoutTests(unittest.TestCase):
    def test_repo_index_lists_this_lab(self) -> None:
        readme = (REPO / "README.md").read_text()
        self.assertIn("20261019-mysql-async-replication-ha", readme)

    def test_compose_services_and_ports(self) -> None:
        compose = (ROOT / "docker" / "docker-compose.yml").read_text()
        for service in ("mysql-1", "mysql-2", "mysql-3", "proxysql", "orchestrator", "sysbench"):
            self.assertIn(service, compose)
        self.assertIn("mysql:8.4.11", compose)
        self.assertIn("proxysql/proxysql:2.7.3", compose)
        self.assertIn("13316:3306", compose)
        self.assertIn("16080:6080", compose)
        self.assertIn("13000:3000", compose)
        self.assertIn("-c", compose)
        self.assertIn("/etc/proxysql.cnf", compose)

    def test_manual_contains_the_deploy_statements(self) -> None:
        deploy = (ROOT / "scripts" / "deploy.sh").read_text()
        manual = manual_bash()
        required = [
            "CREATE USER 'repl'@'%'",
            "CREATE USER 'orchestrator'@'%'",
            "CREATE USER 'monitor'@'%'",
            "CREATE USER 'sbuser'@'%'",
            "CHANGE REPLICATION SOURCE TO",
            "SOURCE_AUTO_POSITION=1",
            "INSERT INTO mysql_replication_hostgroups",
            "mysql-monitor_writer_is_also_reader",
            "/api/discover/mysql-1/3306",
            "/api/clusters-info",
            "oltp_read_write.lua",
            "--db-ps-mode=disable",
            "rm -f /to/auto.cnf",
            "iptables-legacy -P FORWARD ACCEPT",
        ]
        for snippet in required:
            self.assertIn(snippet, deploy, snippet)
            self.assertIn(snippet, manual, snippet)

    def test_orchestrator_hook_and_recovery(self) -> None:
        conf = (ROOT / "docker" / "orchestrator" / "orchestrator.conf.json").read_text()
        self.assertIn("PostMasterFailoverProcesses", conf)
        self.assertIn("proxysql-failover-hook.sh", conf)
        self.assertIn('"RecoverMasterClusterFilters": [".*"]', conf)
        self.assertIn("CHANGE REPLICATION SOURCE TO", (ROOT / "scripts" / "deploy.sh").read_text())
        hook = (ROOT / "docker" / "orchestrator" / "proxysql-failover-hook.sh").read_text()
        self.assertIn("OFFLINE_HARD", hook)
        self.assertIn("hostgroup 10", hook)
        creds = conf
        self.assertIn("SELECT 'repl', 'repl', '', '', ''", creds)

    def test_replica_configs_are_read_only_and_source_is_not(self) -> None:
        source = (ROOT / "docker" / "mysql" / "mysql-1.cnf").read_text()
        self.assertIn("read_only=OFF", source)
        self.assertIn("super_read_only=OFF", source)
        self.assertIn("gtid_mode=ON", source)
        for name in ("mysql-2.cnf", "mysql-3.cnf"):
            text = (ROOT / "docker" / "mysql" / name).read_text()
            self.assertIn("read_only=ON", text)
            self.assertIn("super_read_only=ON", text)

    def test_screenshots_referenced_by_the_readme_exist(self) -> None:
        readme = (ROOT / "README.md").read_text()
        refs = re.findall(r"\((screenshots/[^)]+)\)", readme)
        self.assertGreaterEqual(len(refs), 8)
        for ref in refs:
            self.assertTrue((ROOT / ref).is_file(), ref)


if __name__ == "__main__":
    unittest.main()
