#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${SEEKDB_DATA_DIR:-${project_root}/.seekdb}"
binary="${SEEKDB_BINARY:-seekdb}"
mkdir -p -- "${data_root}/base" "${data_root}/data" "${data_root}/redo"
if [[ -n "${SEEKDB_LIBRARY_PATH:-}" ]]; then
  export LD_LIBRARY_PATH="${SEEKDB_LIBRARY_PATH}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi
exec "${binary}" --nodaemon --base-dir "${data_root}/base" \
  --data-dir "${data_root}/data" --redo-dir "${data_root}/redo" \
  -P "${SEEKDB_PORT:-2881}" --log-level WARN \
  --parameter memory_limit=1G --parameter cpu_count=2 \
  --parameter datafile_size=512M --parameter datafile_maxsize=1G \
  --parameter log_disk_size=2G
