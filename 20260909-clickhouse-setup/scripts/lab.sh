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
  deploy)
    (cd ansible && "$ANSIBLE" playbooks/site.yml "$@")
    ;;
  load-data)
    (cd ansible && "$ANSIBLE" playbooks/load-data.yml "$@")
    ;;
  verify)
    (cd ansible && "$ANSIBLE" playbooks/verify.yml "$@")
    ;;
  teardown)
    (cd ansible && "$ANSIBLE" playbooks/teardown.yml "$@")
    ;;
  test-alert)
    (cd ansible && "$ANSIBLE" playbooks/test-alert.yml "$@")
    ;;
  configure-slack)
    (cd ansible && "$ANSIBLE" playbooks/configure-slack.yml "$@")
    ;;
  *)
    echo "Usage: $0 {bootstrap|deploy|load-data|verify|teardown|test-alert|configure-slack}"
    exit 1
    ;;
esac
