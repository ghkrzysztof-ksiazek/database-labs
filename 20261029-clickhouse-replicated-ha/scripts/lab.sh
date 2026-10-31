#!/usr/bin/env bash
# Same entry points as the other labs in this repository.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cmd="${1:-}"
shift || true

case "$cmd" in
    deploy)   bash "$ROOT/scripts/deploy.sh" "$@" ;;
    verify)   bash "$ROOT/scripts/verify.sh" "$@" ;;
    teardown) bash "$ROOT/scripts/teardown.sh" "$@" ;;
    *)
        echo "Usage: $0 {deploy|verify|teardown}"
        exit 1
        ;;
esac
