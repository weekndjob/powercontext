#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${SEEKDB_BIN:-}" ]]; then
  echo 'Set SEEKDB_BIN to a seekdb >=1.3 executable, or use the default embedded SDK mode.' >&2
  exit 1
fi
base="${SEEKDB_BASE_DIR:-$PWD/.data/server}"
mkdir -p "$base"
exec "$SEEKDB_BIN" --nodaemon --port "${SEEKDB_PORT:-2881}" --base-dir "$base" \
  --parameter memory_limit=4G --parameter memory_budget=4G --log-level WARN
