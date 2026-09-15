#!/usr/bin/env bash
# First Billzebub deployment after bootstrap.sh has prepared the NAS host.
set -euo pipefail

project_root="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/nas/common.sh
source "$project_root/scripts/nas/common.sh"
compose=()
billzebub_init_compose

"${compose[@]}" build api worker
billzebub_up_service postgres
"${compose[@]}" --profile maintenance run --rm migrate
billzebub_up_service api --no-deps
billzebub_up_service worker --no-deps --remove-orphans

if billzebub_wait_for_api_ready; then
  echo "Initial deployment completed and the API is ready."
  exit 0
fi

echo "Initial deployment did not become ready; inspect local service logs." >&2
exit 1
