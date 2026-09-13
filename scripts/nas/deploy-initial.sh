#!/usr/bin/env bash
# First Billzebub deployment after bootstrap.sh has prepared the NAS host.
set -euo pipefail

project_root="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
docker_bin="${DOCKER_BIN:-docker}"
if ! command -v "$docker_bin" >/dev/null 2>&1 && [[ -x /usr/local/bin/docker ]]; then
  docker_bin=/usr/local/bin/docker
fi
command -v "$docker_bin" >/dev/null 2>&1 || {
  echo "Docker is unavailable." >&2
  exit 1
}
compose=("$docker_bin" compose --project-name billzebub --file "$project_root/compose.nas.yaml")

"${compose[@]}" build api worker
"${compose[@]}" up --detach postgres
"${compose[@]}" --profile maintenance run --rm migrate
"${compose[@]}" up --detach api worker

for _attempt in $(seq 1 30); do
  if python3 -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).read()" \
    >/dev/null 2>&1; then
    echo "Initial deployment completed and the API is ready."
    exit 0
  fi
  sleep 2
done

echo "Initial deployment did not become ready; inspect local service logs." >&2
exit 1
