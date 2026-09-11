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
  failover)
    (cd ansible && "$ANSIBLE" playbooks/failover.yml "$@")
    ;;
  backup)
    (cd ansible && "$ANSIBLE" playbooks/backup.yml "$@")
    ;;
  restore)
    (cd ansible && "$ANSIBLE" playbooks/restore.yml "$@")
    ;;
  scale-out)
    (cd ansible && "$ANSIBLE" playbooks/scale-out.yml "$@")
    ;;
  teardown)
    (cd ansible && "$ANSIBLE" playbooks/teardown.yml "$@")
    ;;
  *)
    echo "Usage: $0 {bootstrap|test|deploy|load-data|verify|failover|backup|restore|scale-out|teardown}"
    exit 1
    ;;
esac
