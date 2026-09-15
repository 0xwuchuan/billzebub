#!/usr/bin/env bash
# Build the new image while serving, back up live PostgreSQL, migrate, then
# recreate API and worker with a readiness gate. PostgreSQL is never stopped.
# Tailscale Serve is not modified.
set -euo pipefail

project_root="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/nas/common.sh
source "$project_root/scripts/nas/common.sh"
compose=()
billzebub_init_compose

backup_script="${BILLZEBUB_BACKUP_SCRIPT:-$project_root/scripts/nas/backup.sh}"

"${compose[@]}" build api worker
"$backup_script"
billzebub_up_service postgres --no-recreate
"${compose[@]}" --profile maintenance run --rm migrate

api_recreate_started_at="$(date +%s)"
billzebub_up_service api --no-deps
if ! billzebub_wait_for_api_ready; then
  echo "API recreate finished but readiness did not succeed; inspect local service logs." >&2
  exit 1
fi
api_ready_at="$(date +%s)"
api_recreate_seconds=$((api_ready_at - api_recreate_started_at))

billzebub_up_service worker --no-deps --remove-orphans
if ! billzebub_wait_for_api_ready; then
  echo "Worker recreate finished but API readiness did not succeed; inspect local service logs." >&2
  exit 1
fi

echo "Upgrade completed and the API is ready. API recreate window was ${api_recreate_seconds}s."
