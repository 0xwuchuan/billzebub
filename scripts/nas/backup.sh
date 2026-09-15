#!/usr/bin/env bash
# Create and verify a PostgreSQL logical backup in private host storage.
# Run on the NAS; output never includes a backup filename or database contents.
set -euo pipefail
umask 077

project_root="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
docker_bin="${DOCKER_BIN:-docker}"
if ! command -v "$docker_bin" >/dev/null 2>&1 && [[ -x /usr/local/bin/docker ]]; then
  docker_bin=/usr/local/bin/docker
fi
command -v "$docker_bin" >/dev/null 2>&1 || {
  echo "Docker is unavailable." >&2
  exit 1
}
backup_root="${BILLZEBUB_BACKUP_ROOT:-/volume1/docker/billzebub/backups}"
secrets_root="${BILLZEBUB_SECRETS_ROOT:-/volume1/docker/billzebub/secrets}"
password_file="$secrets_root/postgres-password"
compose=("$docker_bin" compose --project-name billzebub --file "$project_root/compose.nas.yaml")

if [[ ! -d "$backup_root" || -L "$backup_root" ]]; then
  echo "Private backup storage is unavailable." >&2
  exit 1
fi
if [[ ! -d "$secrets_root" || -L "$secrets_root" || ! -f "$password_file" || -L "$password_file" ]]; then
  echo "Database secret is unavailable." >&2
  exit 1
fi
PGPASSWORD="$(cat -- "$password_file" 2>/dev/null)" || PGPASSWORD=""
if [[ -z "$PGPASSWORD" ]]; then
  echo "Database secret is unavailable." >&2
  exit 1
fi

temporary="$(mktemp "$backup_root/.pending.XXXXXXXX")"
final="$backup_root/$(date -u +%Y%m%dT%H%M%SZ).dump"
cleanup() {
  rm -f -- "$temporary"
  unset PGPASSWORD
}
trap cleanup EXIT

export PGPASSWORD
"${compose[@]}" exec -T -e PGPASSWORD postgres pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --username=billzebub \
  --dbname=billzebub >"$temporary"
unset PGPASSWORD
"${compose[@]}" exec -T postgres pg_restore --list <"$temporary" >/dev/null
chmod 0600 "$temporary"
mv -- "$temporary" "$final"
find "$backup_root" -xdev -type f -name '*.dump' -mtime +30 -delete
trap - EXIT

echo "Database backup completed and verified."
