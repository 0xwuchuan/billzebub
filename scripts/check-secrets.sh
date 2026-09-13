#!/usr/bin/env bash
set -euo pipefail

# Scan tracked and non-ignored working-tree files. Lockfiles contain integrity
# hashes by design; the development-only PostgreSQL password is public test
# configuration rather than a credential.
git ls-files --cached --others --exclude-standard -z \
  | xargs -0 uv run detect-secrets-hook \
      --no-verify \
      --exclude-files '(^|/)(pnpm-lock\.yaml|uv\.lock)$' \
      --exclude-lines 'billzebub-development-only'

echo "secret check passed"
