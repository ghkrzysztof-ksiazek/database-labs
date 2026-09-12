#!/usr/bin/env bash
# Wrapper used when system `make` is unavailable.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${ROOT}/.venv"
ANSIBLE="${VENV}/bin/ansible-playbook"

cmd="${1:-}"
shift || true

case "$cmd" in
  bootstrap)
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -U pip
    "$VENV/bin/pip" install -r requirements.txt
    "$VENV/bin/ansible-galaxy" collection install -r ansible/requirements.yml -p ansible/collections
    ;;
  test)
    "$VENV/bin/python" -m unittest discover -s tests -v
    ;;
  deploy)
    (cd ansible && "$ANSIBLE" playbooks/site.yml "$@")
    ;;
  load-data)
    (cd ansible && "$ANSIBLE" playbooks/load-data.yml "$@")
    ;;
  verify)
    (cd ansible && "$ANSIBLE" playbooks/verify.yml "$@")
    ;;
  backup)
    (cd ansible && "$ANSIBLE" playbooks/backup.yml "$@")
    ;;
  restore)
    (cd ansible && "$ANSIBLE" playbooks/restore.yml "$@")
    ;;
  test-backups)
    (cd ansible && "$ANSIBLE" playbooks/tests/all.yml -e run_id="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}" "$@")
    ;;
  report)
    (cd ansible && "$ANSIBLE" playbooks/tests/report.yml -e run_id="${RUN_ID:?set RUN_ID}" "$@")
    ;;
  t0[1-9]|t1[0-2])
    playbook=$(basename "$(ls ansible/playbooks/tests/${cmd}-*.yml | head -1)")
    (cd ansible && "$ANSIBLE" "playbooks/tests/$playbook" -e run_id="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}" "$@")
    ;;
  teardown)
    (cd ansible && "$ANSIBLE" playbooks/teardown.yml "$@")
    ;;
  *)
    echo "Usage: $0 {bootstrap|test|deploy|load-data|verify|backup|restore|test-backups|t01..t12|report|teardown}"
    exit 1
    ;;
esac
