#!/usr/bin/env bash
# Replace the temporary Apple probe route only after the production API is ready.
set -euo pipefail

if [[ "${1:-}" != "--replace-probe" ]]; then
  echo "Pass --replace-probe only after verifying the production API locally." >&2
  exit 2
fi

tailscale_bin="${TAILSCALE_BIN:-tailscale}"
python3 - <<'PY'
import urllib.request

urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=2).read()
PY
"$tailscale_bin" serve --bg --yes 8000

echo "Tailscale Serve now targets the production API."
