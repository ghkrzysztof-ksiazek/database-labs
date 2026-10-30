#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# loadgen is started with docker run, not Compose, so remove it first
docker rm -f loadgen >/dev/null 2>&1 || true
docker compose -f "$ROOT/docker/docker-compose.yml" down -v --remove-orphans
rm -f "$ROOT"/out/*.txt "$ROOT"/out/*.err
echo "lab removed"
