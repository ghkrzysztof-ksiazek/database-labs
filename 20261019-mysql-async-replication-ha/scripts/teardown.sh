#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker compose -f "$ROOT/docker/docker-compose.yml" down -v --remove-orphans
echo "lab removed"
