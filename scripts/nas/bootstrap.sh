#!/usr/bin/env bash
# Prepare the private NAS directories and host-managed secrets for Billzebub.
# Run as root on the NAS. It never prints generated secrets or their paths.
set -euo pipefail

runtime_env_file="${BILLZEBUB_RUNTIME_ENV_FILE:-/volume1/docker/billzebub/runtime.env}"
state_root="/volume1/docker/billzebub"
secrets_root="$state_root/secrets"

usage() {
  echo "Usage: bootstrap.sh [--verify|--configure-runtime]" >&2
}

host_layout_is_safe() {
  for directory in "$state_root" "$secrets_root" "$state_root/artifacts" \
    "$state_root/backups" "$state_root/postgres" "/volume1/Billzebub-Inbox"; do
    [[ -d "$directory" && ! -L "$directory" ]] || return 1
  done
  for secret in "$secrets_root/database-url" "$secrets_root/postgres-password"; do
    [[ -f "$secret" && ! -L "$secret" ]] || return 1
  done
}

runtime_values_are_valid() {
  python3 - <<'PY'
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    allowlist = json.loads(os.environ["BILLZEBUB_TAILSCALE_ALLOWED_LOGINS"])
    timezone = os.environ["BILLZEBUB_APPLE_WALLET_TIMEZONE"]
    if not isinstance(allowlist, list) or not allowlist or not all(
        isinstance(login, str) and login.strip() for login in allowlist
    ):
        raise ValueError
    ZoneInfo(timezone)
except (KeyError, TypeError, ValueError, json.JSONDecodeError, ZoneInfoNotFoundError):
    raise SystemExit(1)
PY
}

runtime_file_is_valid() {
  [[ -f "$runtime_env_file" && ! -L "$runtime_env_file" ]] || return 1
  python3 - "$runtime_env_file" <<'PY'
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    values = {}
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    allowlist = json.loads(values["BILLZEBUB_TAILSCALE_ALLOWED_LOGINS"])
    timezone = values["BILLZEBUB_APPLE_WALLET_TIMEZONE"]
    if not isinstance(allowlist, list) or not allowlist or not all(
        isinstance(login, str) and login.strip() for login in allowlist
    ):
        raise ValueError
    ZoneInfo(timezone)
except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, ZoneInfoNotFoundError):
    raise SystemExit(1)
PY
}

write_runtime_configuration() {
  runtime_values_are_valid || {
    echo "Owner allowlist or Apple Wallet timezone is invalid." >&2
    exit 1
  }
  install -d -m 0700 "$(dirname "$runtime_env_file")"
  temporary="$(mktemp "$(dirname "$runtime_env_file")/.runtime.env.XXXXXXXX")"
  cleanup() {
    rm -f -- "$temporary"
  }
  trap cleanup RETURN
  {
    printf 'BILLZEBUB_TAILSCALE_ALLOWED_LOGINS=%s\n' "$BILLZEBUB_TAILSCALE_ALLOWED_LOGINS"
    printf 'BILLZEBUB_APPLE_WALLET_TIMEZONE=%s\n' "$BILLZEBUB_APPLE_WALLET_TIMEZONE"
  } >"$temporary"
  chmod 0600 "$temporary"
  if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown "$SUDO_UID:$SUDO_GID" "$temporary"
  fi
  mv -- "$temporary" "$runtime_env_file"
  trap - RETURN
}

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this setup command as root on the NAS." >&2
  exit 1
fi

case "${1:-}" in
  --verify)
    [[ $# == 1 ]] || { usage; exit 2; }
    if ! host_layout_is_safe || ! runtime_file_is_valid; then
      echo "NAS runtime setup is incomplete or unsafe." >&2
      exit 1
    fi
    echo "NAS runtime setup is already prepared."
    exit 0
    ;;
  --configure-runtime)
    [[ $# == 1 ]] || { usage; exit 2; }
    host_layout_is_safe || {
      echo "NAS runtime setup is incomplete or unsafe." >&2
      exit 1
    }
    write_runtime_configuration
    echo "NAS runtime configuration updated."
    exit 0
    ;;
  "")
    ;;
  *)
    usage
    exit 2
    ;;
esac

if [[ -z "${BILLZEBUB_TAILSCALE_ALLOWED_LOGINS:-}" || -z "${BILLZEBUB_APPLE_WALLET_TIMEZONE:-}" ]]; then
  echo "Set the owner allowlist JSON and Apple Wallet IANA timezone before setup." >&2
  exit 1
fi
if [[ -e "$runtime_env_file" ]]; then
  echo "Runtime configuration already exists; refusing to replace it." >&2
  exit 1
fi
if ! runtime_values_are_valid; then
  echo "Owner allowlist or Apple Wallet timezone is invalid." >&2
  exit 1
fi

install -d -m 0700 "$state_root" "$state_root/backups"
install -d -m 0710 -o root -g 10001 "$secrets_root"
install -d -m 0700 -o 10001 -g 10001 "$state_root/artifacts"
install -d -m 0700 "$state_root/postgres"
install -d -m 0700 -o 10001 -g 10001 "/volume1/Billzebub-Inbox"

umask 077
password_file="$secrets_root/postgres-password"
database_url_file="$secrets_root/database-url"
if [[ -e "$password_file" || -e "$database_url_file" ]]; then
  echo "Database secrets already exist; refusing to replace them." >&2
  exit 1
fi

password="$(openssl rand -hex 32)"
printf '%s\n' "$password" >"$password_file"
printf 'postgresql+psycopg://billzebub:%s@postgres:5432/billzebub\n' "$password" >"$database_url_file"  # pragma: allowlist secret
unset password
chmod 0600 "$password_file" "$database_url_file"
chown 10001:10001 "$database_url_file"
write_runtime_configuration

echo "NAS runtime directories and host-managed secrets are ready."
