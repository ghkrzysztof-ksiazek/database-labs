# Recorded runs

Each JSONL line is a scenario attempt recorded by Ansible. Reusing a run ID appends attempts, so a development run can contain both failed and passing attempts for the same scenario. Do not treat that as one clean suite run.

- `early-*`: evidence originally written under the incorrect Ansible-relative results path; preserved here without changing its contents.
- `shakeout*`: development runs that exposed harness and recovery defects.
- `recovery-*`: restores used to return the source to the known-good dataset.
- `storage-codex-*`, `pitr-codex-*`, `t12-codex-*`: targeted validation while fixing those defects.
- [`20260912T101400Z-validation-run.md`](20260912T101400Z-validation-run.md): complete ordered validation, all twelve scenarios passed.
- `20260912T101000Z-final`: an earlier interrupted attempt; despite its chosen run name, its report correctly shows failure at t04.

The generated Markdown reports retain attempt-level status and duration. A partial report does not establish that unrun scenarios passed. Reports describe this local dataset and pinned images, not production recovery-time guarantees.

The first targeted `t12-codex-20260912` report captured replication status before the later GTID wait completed. Its source watermark and data comparison passed, but the YAML thread-poll conditions were corrected afterward. Use the ordered validation report for the final quoted conditions and zero-lag status check.
