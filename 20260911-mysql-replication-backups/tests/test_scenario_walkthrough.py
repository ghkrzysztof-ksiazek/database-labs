"""Role source vs reader-facing walkthrough: every t01–t12 scenario.

Drives the shipped Ansible roles and docs/blog-draft.md. Distinctive
kubectl / mysql / mc / CR strings are taken from the role files, not from
hardcoded essay text.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible" / "roles"
BLOG = ROOT / "docs" / "blog-draft.md"

SCENARIOS = (
    ("t01", "t01_backup_full", "On-demand full backup to MinIO"),
    ("t02", "t02_backup_from_replica", "Backup taken from the replica, primary untouched"),
    ("t03", "t03_backup_incremental", "Incremental backup on a full base"),
    ("t04", "t04_storage_contents", "Backup and binlog objects present in MinIO"),
    ("t05", "t05_backup_scheduled", "Scheduled backup runs unattended"),
    ("t06", "t06_backup_retention", "Retention prunes scheduled backups down to keep"),
    ("t07", "t07_restore_in_place", "Whole-cluster restore rolls back post-backup writes"),
    ("t08", "t08_restore_dropped_table", "Restore recovers a dropped table"),
    ("t09", "t09_pitr_timestamp", "Point-in-time recovery to a timestamp"),
    ("t10", "t10_pitr_gtid", "Point-in-time recovery to a GTID"),
    ("t11", "t11_pitr_invalid_target", "An impossible recovery target fails cleanly"),
    ("t12", "t12_restore_as_replica", "Restore into a new cluster, attach as a replica, catch up"),
)

# Operator-facing strings the roles actually apply or exec. Only those present
# in a given role are required to appear in that scenario's narrative.
ROLE_NEEDLES = (
    "PerconaServerMySQLBackup",
    "PerconaServerMySQLRestore",
    "PerconaServerMySQL",
    "sourcePod",
    "incrementalBaseBackupName",
    "backupName",
    "backupSource",
    "type: incremental",
    "type: full",
    "type: date",
    "type: gtid",
    "DROP TABLE",
    "FLUSH BINARY LOGS",
    "CHECKSUM TABLE",
    "CHANGE REPLICATION SOURCE TO",
    "SOURCE_AUTO_POSITION",
    "canary_after_backup",
    "sbtest10",
    "GTID_SUBTRACT",
    "2001-01-01T00:00:00",
    "percona.com/backup-type",
    "mc du",
    "mc ls",
    "kubectl get",
    "kubectl exec",
    "kubectl apply",
    "kubectl -n",
)

BY_HAND = re.compile(
    r"by hand|manually|without ansible|kubectl apply",
    re.IGNORECASE,
)

HEADING = re.compile(r"^## .+", re.M)


def role_text(role_dir: str) -> str:
    root = ANSIBLE / role_dir
    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.suffix in {".yml", ".yaml", ".j2", ".py"} and path.is_file():
            parts.append(path.read_text())
    return "\n".join(parts)


def distinctive_from_role(text: str) -> list[str]:
    found = [n for n in ROLE_NEEDLES if n in text]
    found.extend(re.findall(r"\b(t\d{2}-[\w]+)\b", text))
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def split_sections(markdown: str) -> dict[str, str]:
    """Map t01..t12 to the heading block that names that scenario."""
    matches = list(HEADING.finditer(markdown))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        heading = match.group(0)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end]
        for sid, _, title in SCENARIOS:
            if sid in sections:
                continue
            if re.search(rf"\b{sid}\b", heading) or (
                title.lower() in heading.lower() and sid[:3] in heading.lower()
            ):
                sections[sid] = body
    # t12's walkthrough currently lives under "Restore the backup as a replica"
    # before a later duration-table mention of t12. Prefer the long section.
    if "t12" not in sections:
        for i, match in enumerate(matches):
            heading = match.group(0).lower()
            if "restore the backup as a replica" in heading or "restore as a replica" in heading:
                end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
                sections["t12"] = markdown[match.start() : end]
                break
    return sections


def prose_paragraphs(section: str) -> list[str]:
    """Drop fences and tables; keep wrapped paragraph blocks."""
    no_fences = re.sub(r"```.*?```", "\n", section, flags=re.S)
    blocks = re.split(r"\n\s*\n", no_fences)
    paras: list[str] = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.lstrip().startswith(("#", "|", "-", "*", ">")) for ln in lines):
            continue
        text = " ".join(ln.strip() for ln in lines if not ln.lstrip().startswith(("|", "-", "*", "#")))
        if len(text) >= 180 and not text.startswith(("```", "|")):
            paras.append(text)
    return paras


class ScenarioWalkthroughTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.blog = BLOG.read_text()
        cls.sections = split_sections(cls.blog)

    def test_every_scenario_has_a_named_section(self) -> None:
        for sid, _, title in SCENARIOS:
            self.assertIn(sid, self.sections, f"{sid} ({title}) has no heading section in blog-draft.md")
            self.assertIn(title, self.sections[sid], f"{sid} section is missing its catalogue title")

    def test_every_scenario_has_paragraph_prose_not_a_bullet(self) -> None:
        for sid, _, title in SCENARIOS:
            paras = prose_paragraphs(self.sections.get(sid, ""))
            self.assertTrue(
                paras,
                f"{sid} ({title}) has no paragraph-length prose (only bullets/tables/fences)",
            )
            self.assertGreaterEqual(
                max(len(p) for p in paras),
                180,
                f"{sid} prose is too short to explain the steps",
            )

    def test_every_scenario_shows_a_by_hand_path(self) -> None:
        for sid, _, title in SCENARIOS:
            section = self.sections.get(sid, "")
            self.assertRegex(
                section,
                BY_HAND,
                f"{sid} ({title}) has no by-hand / manual / kubectl apply path",
            )

    def test_every_scenario_quotes_role_commands(self) -> None:
        for sid, role_dir, title in SCENARIOS:
            role = role_text(role_dir)
            section = self.sections.get(sid, "")
            self.assertTrue(
                any(token in section for token in ("kubectl", "mysql", "mc ", "kind:")),
                f"{sid} ({title}) shows none of kubectl / mysql / mc / kind:",
            )
            needles = distinctive_from_role(role)
            self.assertTrue(needles, f"{sid} role produced no distinctive operator-facing strings")
            overlap = [n for n in needles if n in section]
            self.assertTrue(
                overlap,
                f"{sid} ({title}) quotes none of the role's operator-facing strings {needles[:8]}",
            )

    def test_pitr_is_defined_near_t09_t10_t11(self) -> None:
        pitr_blob = "\n".join(self.sections.get(sid, "") for sid in ("t09", "t10", "t11"))
        self.assertRegex(
            pitr_blob,
            r"point[- ]in[- ]time recovery",
            "PITR is not expanded to point-in-time recovery in the t09–t11 material",
        )

    def test_first_use_terms_are_expanded(self) -> None:
        text = self.blog
        expansions = {
            "GTID": r"GTID.{0,80}(global transaction|transaction identifier)",
            "MinIO": r"MinIO.{0,80}(S3|object storage)",
            "XtraBackup": r"XtraBackup.{0,80}(physical|datadir|data directory)",
            "PerconaServerMySQLBackup": r"PerconaServerMySQLBackup.{0,120}(custom resource|Kubernetes object|backup object)",
            "sourcePod": r"sourcePod.{0,160}(replica|pod)",
            "keep": r"keep.{0,80}(prun|retain|oldest)",
            "binlog server": r"binlog server.{0,160}(replica|binary log|object storage)",
            "gtid_purged": r"gtid_purged.{0,160}(transaction|XtraBackup|auto-position|SOURCE_AUTO_POSITION)",
        }
        for term, pattern in expansions.items():
            compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
            self.assertRegex(
                text,
                compiled,
                msg=f"{term} is used without an in-place expansion matching {pattern}",
            )


if __name__ == "__main__":
    unittest.main()
