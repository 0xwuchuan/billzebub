#!/usr/bin/env bash
# Restore the newest private logical backup into an isolated disposable PostgreSQL container.
set -euo pipefail

backup_root="${BILLZEBUB_BACKUP_ROOT:-/volume1/docker/billzebub/backups}"
docker_bin="${DOCKER_BIN:-docker}"
if ! command -v "$docker_bin" >/dev/null 2>&1 && [[ -x /usr/local/bin/docker ]]; then
  docker_bin=/usr/local/bin/docker
fi
command -v "$docker_bin" >/dev/null 2>&1 || {
  echo "Docker is unavailable." >&2
  exit 1
}
latest=""
for candidate in "$backup_root"/*.dump; do
  [[ -f "$candidate" ]] || continue
  if [[ -z "$latest" || "$candidate" -nt "$latest" ]]; then
    latest="$candidate"
  fi
done
if [[ -z "$latest" ]]; then
  echo "No private database backup is available for a restore drill." >&2
  exit 1
fi

container="billzebub-restore-drill-$$"
cleanup() {
  "$docker_bin" rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$docker_bin" run --detach --rm --name "$container" --network none \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=1g \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:16.11-bookworm >/dev/null
for _attempt in $(seq 1 30); do
  if "$docker_bin" exec "$container" pg_isready -U postgres >/dev/null; then
    break
  fi
  sleep 2
done
"$docker_bin" exec "$container" pg_isready -U postgres >/dev/null
"$docker_bin" exec "$container" createdb -U postgres billzebub
"$docker_bin" exec -i "$container" pg_restore --no-owner --no-privileges -U postgres -d billzebub <"$latest"
"$docker_bin" exec "$container" psql -U postgres -d billzebub -Atqc \
  "SELECT 1 FROM alembic_version LIMIT 1" | grep -qx "1"

echo "Restore drill completed successfully."
