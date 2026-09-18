# External Codex categorizer

Billzebub's in-app pass assigns a Category only at deterministic high confidence and leaves everything else as a `categorization_needed` Review. Unknowns are handled **outside** the NAS app containers. **Jev is the primary external pass** (`docs/jev-categorizer.md`); this Codex ChatGPT runner (`codex exec`) remains an **optional fallback** and must not be removed. It is not a Grok Bot and must not be added to `compose.nas.yaml`.

The runner talks only to the agent-safe API from ADR 0003: opaque Transaction IDs, Counterparty, amount, currency, effective date, Transaction kind, Categories, and review choices. Schedule it as a forge routine. Keep the bearer token on rafiki as a mode-`0600` secret.

## What it does

1. `GET /api/v1/agent/reviews` (scope `agent:read`). That resource is already limited to pending `categorization_needed` Reviews.
2. Exits 0 with **no stdout** when the queue is empty.
3. Loads `GET /api/v1/agent/categories` and `GET /api/v1/agent/transactions/{id}`.
4. Skips Transfers, Income, Refunds, Reimbursements, and Expenses that already have a non-`Uncategorized` split. Those Reviews are left untouched.
5. For each remaining Expense or Cash Withdrawal, runs `codex exec` non-interactively with a tight prompt and `--output-schema`. Codex may propose only an existing catalog Category.
6. Applies `action=apply` proposals at or above the confidence threshold via `POST /api/v1/agent/transactions/{id}/category` with `Idempotency-Key` and `If-Match`. Ambiguous, low-confidence, unknown, or mismatched proposals are skipped (fail closed; the Review stays).

## Invoke

Prefer `gpt-5.6-luna`. If that `codex exec` fails, the runner retries once with `gpt-5.6-terra`.

```bash
export BILLZEBUB_API_BASE="https://rafiki.tail7c684e.ts.net"
export BILLZEBUB_AGENT_TOKEN_FILE="/private/path/codex-categorizer.token"

uv run python -m scripts.agent.codex_categorize
```

Equivalent:

```bash
uv run python scripts/agent/codex_categorize.py \
  --token-file /private/path/codex-categorizer.token
```

Dry-run (Codex is called; categorize is not POSTed). Do this **once on forge** before enabling the standing routine:

```bash
uv run python -m scripts.agent.codex_categorize --dry-run
```

Primary model override and terra fallback remain explicit:

```bash
codex exec -m gpt-5.6-luna --output-schema /tmp/proposal.schema.json "$PROMPT"
codex exec -m gpt-5.6-terra --output-schema /tmp/proposal.schema.json "$PROMPT"
```

The Python runner adds `--skip-git-repo-check`, `--sandbox read-only`, `--ephemeral`, and `-o` so a forge routine does not need an interactive TTY or a Git checkout.

## Environment

| Variable | Required | Meaning |
|---|---|---|
| `BILLZEBUB_API_BASE` | yes | Agent API origin, no trailing path. `BILLZEBUB_API_URL` is accepted as an alias. HTTPS is required except on loopback. |
| `BILLZEBUB_AGENT_TOKEN` | one of token or file | Bearer token. Never commit, log, or pass as a CLI flag. |
| `BILLZEBUB_AGENT_TOKEN_FILE` | one of token or file | Path to a regular mode-`0600` file containing the token. `--token-file` is the same. |
| `BILLZEBUB_CODEX_MODEL` | no | Default `gpt-5.6-luna`. |
| `BILLZEBUB_CODEX_FALLBACK_MODEL` | no | Default `gpt-5.6-terra`. |
| `BILLZEBUB_CODEX_MIN_CONFIDENCE` | no | Default `0.95`. Below this, the Review is left pending. |
| `BILLZEBUB_CODEX_LIMIT` | no | Max Reviews processed in one run. |
| `BILLZEBUB_CODEX_TIMEOUT_SECONDS` | no | Per-`codex exec` timeout. Default `120`. |
| `BILLZEBUB_CODEX_BIN` | no | Codex executable. Default `codex`. |

The child `codex` process does not inherit `BILLZEBUB_AGENT_TOKEN`. Codex authentication stays in the host Codex ChatGPT login (`~/.codex/auth.json`) or a host-managed `CODEX_API_KEY`. Do not put either in Git.

## Token on rafiki

Issue the token **on rafiki** (the NAS). The plaintext stays there as a mode-`0600` secret: not Git, not chat, not `compose.nas.yaml`, and not the Compose-mounted `/volume1/docker/billzebub/secrets` directory the app containers read.

In the Billzebub maintenance container on rafiki:

```bash
billzebub token issue --name "Codex categorizer" --kind agent \
  --scope agent:read --scope agent:categorize
```

Write the plaintext once to a rafiki-local `0600` file **outside** the checkout:

```bash
install -m 600 /dev/stdin /private/path/codex-categorizer.token
# paste the token once, then EOF
```

Forge reads that secret through `BILLZEBUB_AGENT_TOKEN_FILE` (or `--token-file`). Do not paste the token into a forge config committed to this repo. Rotate with `billzebub token rotate <token-id>` if the file may have leaked. The runner never prints the token.

## Schedule (forge routine)

The primary schedule is a **forge cron/routine**, not NAS Task Scheduler and not a job inside the `api` or `worker` containers. Forge already has Codex ChatGPT auth; it calls rafiki's agent API over Tailscale.

After this runner ships:

1. Keep the bearer on rafiki as the `0600` secret above.
2. On forge, dry-run **once**:

```bash
BILLZEBUB_API_BASE="https://rafiki.tail7c684e.ts.net" \
BILLZEBUB_AGENT_TOKEN_FILE="/private/path/codex-categorizer.token" \
  uv run python -m scripts.agent.codex_categorize --dry-run
```

3. If that is quiet or prints only `codex categorizer dry-run applied=0 skipped=… failed=0`, enable the **standing forge routine** with the same environment and without `--dry-run`:

```bash
BILLZEBUB_API_BASE="https://rafiki.tail7c684e.ts.net" \
BILLZEBUB_AGENT_TOKEN_FILE="/private/path/codex-categorizer.token" \
  uv run python -m scripts.agent.codex_categorize
```

Do not add a Synology Task Scheduler copy as the default path. NAS cron would still be the wrong place to run Codex.

An empty queue is a quiet success (exit 0, no stdout). Non-empty runs print one line: `codex categorizer applied=N skipped=M failed=P`.

## Fail-closed policy

The runner applies a Category only when all of these hold:

- Transaction kind is `expense` or `cash_withdrawal`
- Review choices include `categorize`
- Codex returns `action=apply`
- `category_id` exists in the current catalog
- `category_name` matches that catalog row
- `confidence` is at least `BILLZEBUB_CODEX_MIN_CONFIDENCE`

Anything else, including a Codex failure after both luna and terra, leaves the Review in place.
