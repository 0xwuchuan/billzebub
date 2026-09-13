#!/usr/bin/env bash
# Publish only Git-visible source files to a temporary NAS directory, then swap atomically.
# Run from this repository on the Mac; ignored private data is never part of the archive.
set -euo pipefail

remote_host="${BILLZEBUB_NAS_HOST:-wuchuan@rafiki.tail7c684e.ts.net}"
remote_root="${BILLZEBUB_NAS_APP_ROOT:-/volume1/docker/billzebub/app}"
remote_parent="$(dirname -- "$remote_root")"

uv run python scripts/check_private_files.py >/dev/null
ssh -o BatchMode=yes "$remote_host" "mkdir -p -- '$remote_parent'"

staging_name=".app-staging-$$"
ssh -o BatchMode=yes "$remote_host" "rm -rf -- '$remote_parent/$staging_name'; mkdir -- '$remote_parent/$staging_name'"
cleanup() {
  ssh -o BatchMode=yes "$remote_host" "rm -rf -- '$remote_parent/$staging_name'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git ls-files --cached --others --exclude-standard -z \
  | COPYFILE_DISABLE=1 tar --no-xattrs --null --files-from=- -cf - \
  | ssh -o BatchMode=yes "$remote_host" "tar -xf - -C '$remote_parent/$staging_name'"

ssh -o BatchMode=yes "$remote_host" "
  set -eu
  test -f '$remote_parent/$staging_name/compose.nas.yaml'
  test -f '$remote_parent/$staging_name/scripts/nas/cutover-wizard.sh'
  rm -rf -- '$remote_parent/.app-previous'
  if test -e '$remote_root'; then mv -- '$remote_root' '$remote_parent/.app-previous'; fi
  mv -- '$remote_parent/$staging_name' '$remote_root'
  rm -rf -- '$remote_parent/.app-previous'
"
trap - EXIT

echo "NAS application source published without private runtime data."
