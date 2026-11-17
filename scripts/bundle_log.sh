#!/usr/bin/env bash
# Run a `databricks bundle ...` command and append its console output, with timestamps,
# to evidence/run_log.txt.  Usage: scripts/bundle_log.sh "<phase label>" validate|deploy|run ... [args]
set -o pipefail
cd "$(dirname "$0")/.."
LABEL="$1"; shift
LOG=evidence/run_log.txt
{
  echo "================================================================================"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${LABEL}"
  echo "\$ databricks bundle $*"
} >> "$LOG"
databricks bundle "$@" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] exit code: ${rc}" >> "$LOG"
exit $rc
