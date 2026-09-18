# shellcheck shell=bash
# Shared NAS Compose helpers. Sourced by deploy-initial.sh and upgrade.sh.
# Never prints secret values, backup filenames, or database contents.

billzebub_init_compose() {
  docker_bin="${DOCKER_BIN:-docker}"
  if ! command -v "$docker_bin" >/dev/null 2>&1 && [[ -x /usr/local/bin/docker ]]; then
    docker_bin=/usr/local/bin/docker
  fi
  command -v "$docker_bin" >/dev/null 2>&1 || {
    echo "Docker is unavailable." >&2
    return 1
  }
  compose=("$docker_bin" compose --project-name billzebub --file "$project_root/compose.nas.yaml")
  compose_wait_flags=()
  # Capture help fully. `grep -q` closes the pipe on the first match; with
  # `set -o pipefail` that SIGPIPEs `docker compose` / the test stub and leaves
  # wait flags unset, so API recreate becomes `up --detach --no-deps api`.
  local compose_help=""
  compose_help="$("${compose[@]}" up --help 2>/dev/null || true)"
  if [[ "$compose_help" == *"--wait"* ]]; then
    compose_wait_flags=(--wait --wait-timeout 120)
  fi
}

billzebub_up_service() {
  local service="$1"
  shift
  "${compose[@]}" up --detach "${compose_wait_flags[@]}" "$@" "$service"
}

billzebub_wait_for_api_ready() {
  local ready_url="${BILLZEBUB_READY_URL:-http://127.0.0.1:8000/health/ready}"
  local attempts="${BILLZEBUB_READY_ATTEMPTS:-30}"
  local delay="${BILLZEBUB_READY_SLEEP:-2}"
  local _attempt
  for _attempt in $(seq 1 "$attempts"); do
    if python3 -c \
      "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2).read()" \
      "$ready_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}
