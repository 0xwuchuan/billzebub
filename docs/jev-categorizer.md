# External Jev categorizer

Billzebub's in-app pass assigns a Category only at deterministic high confidence and leaves everything else as a `categorization_needed` Review. Unknowns are handled **outside** the NAS app containers. **Jev** (TypeSafe System One) is the primary host-side pass; the Codex runner remains an optional fallback and is not deleted. This job is not a Grok Bot and must not be added to `compose.nas.yaml` or the `api`/`worker` images.

The runner talks only to the agent-safe API from ADR 0003: opaque Transaction IDs, Counterparty, amount, currency, effective date, Transaction kind, Categories, and review choices. Schedule it as a forge routine after a dry-run. Keep the Billzebub bearer on rafiki and the TypeSafe key on forge as mode-`0600` secrets.

## Cascade

1. **In-app map + rules** on the NAS (`docs/categorizer.md`) — learned Counterparty map and deterministic keyword rules. No LLM in the app containers.
2. **Jev** (this runner) — primary external pass for remaining `categorization_needed` Reviews.
3. **Codex** (`docs/codex-categorizer.md`) — optional fallback. Do not wire a forge routine swap in this change; keep the Codex script intact.

## What it does

1. `GET /api/v1/agent/reviews` (scope `agent:read`). That resource is already limited to pending `categorization_needed` Reviews.
2. Exits 0 with **no stdout** when the queue is empty.
3. Loads `GET /api/v1/agent/categories` and `GET /api/v1/agent/transactions/{id}`.
4. Skips Transfers, Income, Refunds, Reimbursements, and Expenses that already have a non-`Uncategorized` split. Those Reviews are left untouched.
5. For each remaining Expense or Cash Withdrawal, POSTs `https://api.typesafe.ai/v1/systemone` via `typesafe-sdk` with:
   - `state`: Counterparty, amount, currency, effective date, Transaction kind (agent-safe fields only)
   - `questions.category`: Choice over active catalog Category names (criteria = the name) plus an explicit `uncategorized` skip option
   - `questions.enough_evidence`: Noul — enough evidence to assign confidently
6. Applies a proposal only when fail-closed checks all pass, via `POST /api/v1/agent/transactions/{id}/category` with `Idempotency-Key` and `If-Match`. Anything else leaves the Review in place.

## Invoke

Pin `jev-1.13.0` (override with `BILLZEBUB_JEV_MODEL`). Dry-run **once on forge** before a standing routine:

```bash
export BILLZEBUB_API_BASE="https://rafiki.tail7c684e.ts.net"
export BILLZEBUB_AGENT_TOKEN_FILE="/private/path/jev-categorizer.token"
export TYPESAFE_API_KEY_FILE="/private/path/typesafe.api-key"

uv run python -m scripts.agent.jev_categorize --dry-run
```

Equivalent:

```bash
uv run python scripts/agent/jev_categorize.py \
  --token-file /private/path/jev-categorizer.token \
  --dry-run
```

`--dry-run` still calls Jev; it does not POST categorize. There is no TypeSafe key CLI flag.

Host-side env (from a Billzebub checkout, not the NAS image):

```bash
uv sync --frozen --no-dev --extra agent
uv run python -m scripts.agent.jev_categorize --dry-run
```

`typesafe-sdk` is an optional `agent` extra and a dev-group dependency so tests can mock it. `Dockerfile` / `compose.nas.yaml` keep `uv sync --frozen --no-dev` without extras, so Jev never lands in the `api` or `worker` containers.

If dry-run is quiet or prints only `jev categorizer dry-run applied=0 skipped=… failed=0`, run without `--dry-run`:

```bash
BILLZEBUB_API_BASE="https://rafiki.tail7c684e.ts.net" \
BILLZEBUB_AGENT_TOKEN_FILE="/private/path/jev-categorizer.token" \
TYPESAFE_API_KEY_FILE="/private/path/typesafe.api-key" \
  uv run python -m scripts.agent.jev_categorize
```

An empty queue is a quiet success (exit 0, no stdout). Non-empty runs print one line: `jev categorizer applied=N skipped=M failed=P`.

## Environment

| Variable | Required | Meaning |
|---|---|---|
| `BILLZEBUB_API_BASE` | yes | Agent API origin, no trailing path. `BILLZEBUB_API_URL` is accepted as an alias. HTTPS is required except on loopback. |
| `BILLZEBUB_AGENT_TOKEN` | one of token or file | Bearer token. Never commit, log, or pass as a CLI flag. |
| `BILLZEBUB_AGENT_TOKEN_FILE` | one of token or file | Path to a regular mode-`0600` file containing the token. `--token-file` is the same. |
| `TYPESAFE_API_KEY` | one of key or file | TypeSafe API key. Never commit, log, or pass as a CLI flag. |
| `TYPESAFE_API_KEY_FILE` | one of key or file | Path to a regular mode-`0600` file containing the TypeSafe key. Prefer this on forge. |
| `BILLZEBUB_JEV_MODEL` | no | Default `jev-1.13.0`. |
| `BILLZEBUB_JEV_MIN_CONFIDENCE` | no | Default `0.85`. Below this, the Review is left pending. |
| `BILLZEBUB_JEV_LIMIT` | no | Max Reviews processed in one run. |
| `BILLZEBUB_JEV_TIMEOUT_SECONDS` | no | Per-System-One timeout. Default `30`. |

The runner never prints tokens or API keys. The TypeSafe client receives the key as a constructor argument, not a CLI flag.

### Why 0.85 versus Codex 0.95

Codex `BILLZEBUB_CODEX_MIN_CONFIDENCE` defaults to `0.95` because that number is a model-written field on unstructured JSON, not a calibrated probability. Jev Choice `confidence` is derived from the option distribution (calibrated System One output), and the companion Noul is already a yes-probability. `0.85` is a conservative “act automatically” floor on those calibrated values; both Choice confidence **and** the evidence Noul must clear it.

## Token on rafiki (Billzebub agent)

Issue the token **on rafiki** (the NAS). The plaintext stays there as a mode-`0600` secret: not Git, not chat, not `compose.nas.yaml`, and not the Compose-mounted `/volume1/docker/billzebub/secrets` directory the app containers read.

In the Billzebub maintenance container on rafiki:

```bash
billzebub token issue --name "Jev categorizer" --kind agent \
  --scope agent:read --scope agent:categorize
```

Write the plaintext once to a rafiki-local `0600` file **outside** the checkout:

```bash
install -m 600 /dev/stdin /private/path/jev-categorizer.token
# paste the token once, then EOF
```

Forge reads that secret through `BILLZEBUB_AGENT_TOKEN_FILE` (or `--token-file`). Rotate with `billzebub token rotate <token-id>` if the file may have leaked.

## TypeSafe key on forge

Put `TYPESAFE_API_KEY` only in a forge-local mode-`0600` file, for example `/private/path/typesafe.api-key`. Do not store a live key in this repo, in chat, in `compose.nas.yaml`, or in the NAS app secret directory. Point `TYPESAFE_API_KEY_FILE` at that file. Never pass the key as a CLI flag.

## Fail-closed policy

The runner applies a Category only when all of these hold:

- Transaction kind is `expense` or `cash_withdrawal`
- Review choices include `categorize`
- Jev Choice is a real catalog `category_id` (not `uncategorized` / skip)
- Choice `confidence` is at least `BILLZEBUB_JEV_MIN_CONFIDENCE`
- Noul `enough_evidence` is at least `BILLZEBUB_JEV_MIN_CONFIDENCE`
- `category_name` matches that catalog row uniquely

Anything else, including a TypeSafe failure, leaves the Review in place.
