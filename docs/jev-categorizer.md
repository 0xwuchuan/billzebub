# NAS worker Jev categorizer

The **NAS worker** is the production auto-categorizer. After statement confirmation (and after a Real-time Claim is confirmed into a Transaction) it calls TypeSafe **Jev** with agent-safe fields only and applies a Category when confidence is at least **0.5**. The same Choice path also categorizes claim-only provisional Apple Wallet rows before a Statement arrives. Below that floor it leaves the row uncategorized (fail closed), unless the Choice is a child whose sibling probabilities sum to at least 0.5: then the worker applies the parent and keeps the Review open. This is not a Grok Bot and is not scheduled on forge.

`scripts/agent/jev_categorize.py` is an **optional ops CLI** for dry-runs against the agent API. It is not required for production once `TYPESAFE_API_KEY` is on rafiki for the worker.

## Cascade

1. **Owner** — explicit categorization in the owner workspace. That decision is evidence for merchant memory.
2. **Merchant memory** — before Jev, an unambiguous `merchant_category_memory` row for `normalize_counterparty(counterparty)` is applied with reason `merchant_memory` and Jev is not called. One owner Category wins over any Jev seed. Several owner Categories, or several Jev Categories with no owner decision, leave no row.
3. **Worker Jev** — inline after Reconciliation confirmations and after a new claim-only provisional Apple Wallet Real-time Claim, then a daily NAS catch-up for leftovers (including those Claims and Wallet-originated Transactions).

Jev seeds memory only from applies whose confidence is at least 0.9 and whose Category is still the current one. A later owner correction replaces that seed. There is no keyword scorer, Codex runner, or forge webhook.

## What the worker does

1. After `reconcile_financial_account` commits confirmations, enqueue `categorize_transaction` for each new Transaction id (statement-only or matched Real-time Claim).
2. Load the Transaction and active catalog Categories. Skip Transfers, Income, Refunds, Reimbursements, and rows that already have a non-`Uncategorized` split.
3. POST `https://api.typesafe.ai/v1/systemone` via `typesafe-sdk` with:
   - `state`: Counterparty, normalized Counterparty, amount, currency, effective date, Transaction kind (agent-safe fields only). `normalized_counterparty` is `normalize_counterparty(counterparty)` and may be empty. When confirmed spends exist, `similar_confirmed_transactions` is a list of up to 8 agent-safe examples (counterparty, normalized counterparty, amount, currency, kind, category). Same normalized merchant ranks first, then token overlap, kind, and amount. No ids.
   - `questions.category`: Choice over active catalog Categories (Uncategorized is excluded; there is no skip / `uncategorized` option). A top-level Category is offered under its name. A child whose parent is in the catalog is offered as `Parent > Child`; grandchildren are omitted. When the parent row is absent, a unique leaf stays the leaf name and colliding leaves use `Parent > Child`. The Choice criteria value is `category.description` when that text is set, otherwise the option label.
4. Apply a proposal only when fail-closed checks all pass, through `OwnerTransactionActions` with reason `jev_categorization`. Anything else leaves the Review in place.
5. After every Jev propose (apply or skip, including TypeSafe failures), append a `jev_categorization_attempt` row and emit an info log line. Catch-up uses this same propose/apply path for leftover Transactions (`categorize_transaction`) and claim-only provisionals (`categorize_claim`).

Claim-only Apple Wallet rows use the same Choice question, 0.5 floor, and catalog mapping. There is still no uncategorized/skip Choice and no Noul `enough_evidence` gate. An apply stores one `claim_category` row (claim id, catalog Category, positive Authorized Amount). On statement Reconciliation, confirmation copies that Category onto the new Transaction and sizes the Category Split to the Posted Amount. A linked Claim is no longer claim-only, so Jev does not categorize it again.

Owner Pending Review for `categorization_needed` joins the latest attempt into `context.jev_attempt` (read-time; the stored Review context is unchanged).

## Attempt log

Each row is append-only and uses the same agent-safe snapshot sent to TypeSafe (no API keys, account ids, artifacts, or raw descriptions):

| Field | Meaning |
|---|---|
| `transaction_id` | Opaque Transaction id, or null when the subject is a Claim |
| `claim_id` | Opaque Claim id for a claim-only provisional, or null for a Transaction |
| `attempted_at` | When the worker finished the propose |
| `model` | Jev model, default `jev-1.13.0` |
| `counterparty`, `amount`, `currency`, `effective_date`, `kind` | State snapshot sent to TypeSafe |
| `choice` | Raw Choice string, including its original spacing, or null when undetermined |
| `choice_confidence`, `noul` | Choice confidence is a unit-interval score, or null. `noul` is unused (null / omitted); the evidence Noul question is no longer asked. |
| `action` | `apply` or `skip` |
| `skip_reason` | Null on apply. On skip: `low_confidence`, `missing_choice`, `missing_confidence`, `unknown_category`, `ambiguous_category`, `jev_unavailable`, or `empty_catalog` |
| `category_id`, `category_name` | Set only when `action` is `apply` |
| `error_class`, `error_message` | Optional TypeSafe/Jev error, already scrubbed of API keys |

The worker info line is `jev attempt action=… confidence=… noul=… category=… transaction_id=…`, where category is the catalog name on apply and `skip` otherwise. `noul` is `-` when omitted.

## Daily NAS catch-up (Wallet leftovers)

The worker loop, not forge, enqueues `jev_catch_up` once per local calendar day at or after **21:00 Asia/Singapore**. That job lists pending `categorization_needed` Reviews and uncategorized claim-only provisional Apple Wallet rows, then enqueues the same Jev propose/apply path. It also requeues failed `categorize_transaction` and `categorize_claim` jobs whose `last_error_code` is `jev_unavailable`. Requeue uses the same dedupe key, so a subject that is already queued or running is not inserted again. An empty queue is a quiet success (the catch-up job completes and enqueues nothing).

TypeSafe errors and timeouts fail the categorize job as `jev_unavailable` and retry with equal-jitter exponential backoff: full delay `min(30 minutes, 30s * 2**(attempt-1))`, jittered to the range from half of that delay through the full delay. Categorize jobs allow 8 attempts.

Owner CLI, dry-run unless `--apply` is passed:

```bash
billzebub jev requeue-failed
billzebub jev requeue-failed --apply
```

The command prints `before failed=… active=…` and `after failed=… active=… requeued=…`. `failed` counts failed categorize jobs with `last_error_code=jev_unavailable`. `active` counts how many of those subjects already have a queued or running job.

Rebuild merchant memory from current Transactions (and claim-only Jev applies). Dry-run unless `--apply` is passed:

```bash
billzebub jev backfill-memory
billzebub jev backfill-memory --apply
```

Dry-run prints `before rules=…`, `would_write=… would_clear=…`, and `after rules=…` equal to the before count. `--apply` prints `written` and `cleared`.

Compare stored Jev choices with the Category now on each Transaction. Read-only. Does not change the 0.5 floor. Coverage is the share of attempts with a confidence and a final Category whose confidence is at least the threshold and that returned a Choice. Precision is the share of those Choices that name the final Category.

```bash
billzebub jev eval-threshold
```

Pending `categorization_needed` Reviews are also grouped by normalized merchant:

- `GET /api/v1/reviews/merchant-groups`
- `POST /api/v1/reviews/merchant-groups/apply` with `If-Match` set to the group `etag`, body `{normalized_key, category_id, exclude_transaction_ids, remember}`. `remember` defaults to true. When it is false the included charges are categorized and the future rule is not kept.
- `POST /api/v1/merchant-memory/forget` with `{normalized_key}` removes one rule.
- `POST /api/v1/reviews/merchant-groups/undo` with `If-Match` set to the apply response `undo_etag`
- `GET /api/v1/merchant-memory`

Apply categorizes the included pending Transactions as the owner (`owner_categorization`), writes exclusions for the ones left out, and refreshes the future rule when the merchant is unambiguous. Both mutations require `X-Billzebub-CSRF: bzb-spa`.

Equivalent cron expression (for documentation only; do not put this on forge):

```
0 21 * * *
```

Timezone: `Asia/Singapore` (`BILLZEBUB_JEV_CATCHUP_TIMEZONE`). Hour: `BILLZEBUB_JEV_CATCHUP_HOUR` (default `21`). Compose does not add a second service; the existing `worker` owns the schedule. Recreate the worker after changing env.

If the worker was down at 21:00 and comes back later the same evening, catch-up still runs (`hour >= 21`). It does not run before 21:00.

## TypeSafe key on rafiki (worker)

Put the key **on rafiki** as a mode-`0600` secret the worker already mounts. Do not store a live key in this repo, in chat, or in `compose.nas.yaml`. Prefer a file in the existing secrets directory:

```bash
install -m 600 -o 10001 -g 10001 /dev/stdin \
  /volume1/docker/billzebub/secrets/typesafe-api-key
# paste the key once, then EOF
```

Then append to `/volume1/docker/billzebub/runtime.env` (already mode `0600`):

```bash
TYPESAFE_API_KEY_FILE=/run/secrets/typesafe-api-key
BILLZEBUB_JEV_MIN_CONFIDENCE=0.5
BILLZEBUB_JEV_MODEL=jev-1.13.0
```

`TYPESAFE_API_KEY` (plaintext in `runtime.env`) is accepted if a file is inconvenient. `BILLZEBUB_TYPESAFE_API_KEY` / `_FILE` are aliases. Recreate the worker so it reloads env (env-only; no migration):

```bash
docker compose -f compose.nas.yaml up -d --force-recreate --no-deps worker
```

The worker image includes `typesafe-sdk`. It joins the Compose `egress` network so it can reach `https://api.typesafe.ai` only; it still publishes no ports. Missing key, unsafe file mode, TypeSafe failure, skip, or confidence below 0.5 leaves Reviews in place.

## Optional ops CLI (not production)

Pin `jev-1.13.0` (override with `BILLZEBUB_JEV_MODEL`). From a Billzebub checkout, not as a substitute for the worker:

```bash
export BILLZEBUB_API_BASE="https://rafiki.tail7c684e.ts.net"
export BILLZEBUB_AGENT_TOKEN_FILE="/private/path/jev-categorizer.token"
export TYPESAFE_API_KEY_FILE="/private/path/typesafe.api-key"

uv run python -m scripts.agent.jev_categorize --dry-run
```

`--dry-run` still calls Jev; it does not POST categorize. There is no TypeSafe key CLI flag. An empty queue is a quiet success (exit 0, no stdout).

The CLI still needs an agent token with `agent:read` and `agent:categorize`. Issue it on rafiki if you use the CLI; the worker does not use that token.

## Environment

| Variable | Required | Meaning |
|---|---|---|
| `TYPESAFE_API_KEY` | one of key or file | TypeSafe API key. Never commit, log, or pass as a CLI flag. |
| `TYPESAFE_API_KEY_FILE` | one of key or file | Path to a regular mode-`0600` file containing the TypeSafe key. Prefer this on rafiki at `/run/secrets/typesafe-api-key`. |
| `BILLZEBUB_JEV_MODEL` | no | Default `jev-1.13.0`. |
| `BILLZEBUB_JEV_MIN_CONFIDENCE` | no | Default `0.5`. Below this, the Review is left pending. |
| `BILLZEBUB_JEV_TIMEOUT_SECONDS` | no | Per-System-One timeout. Default `30`. |
| `BILLZEBUB_JEV_CATCHUP_HOUR` | no | Local hour for daily catch-up. Default `21`. |
| `BILLZEBUB_JEV_CATCHUP_TIMEZONE` | no | IANA timezone for catch-up. Default `Asia/Singapore`. |
| `BILLZEBUB_JEV_LIMIT` | no | CLI only: max Reviews processed in one run. |

The worker never prints tokens or API keys. The TypeSafe client receives the key as a constructor argument, not a CLI flag.

`BILLZEBUB_JEV_MIN_CONFIDENCE` defaults to `0.5`. Only Choice confidence must clear that floor; there is no second Noul gate. Low confidence is the abstain path (leave Uncategorized + `categorization_needed`), unless a child Choice's summed child probabilities clear the floor. In that case the worker applies the parent and leaves the Review open so the owner can keep it or pick a child.

The host CLI (`scripts/agent/jev_categorize.py`) and the NAS worker both call `billzebub.jev` for propose/apply.

## Fail-closed policy

The worker applies a Category only when all of these hold:

- Transaction or Claim kind is `expense` or `cash_withdrawal` (a Claim with no hint is treated as an Expense)
- Choice `confidence` is at least `BILLZEBUB_JEV_MIN_CONFIDENCE`, or the Choice is a child and the summed probabilities of that parent's children clear the floor (the parent is applied)
- Jev Choice maps to one active catalog Category after trim, whitespace collapse, NFKC, and casefold. `Parent > Child` and `Parent/Child` match a nested Category. A leaf name that belongs to more than one Category is `ambiguous_category` unless the Choice is that Category's full path. Uncategorized is never a Choice option.

Anything else, including a missing TypeSafe key or a TypeSafe failure, leaves the row uncategorized and stores `skip_reason`. TypeSafe failures and timeouts retry the `categorize_transaction` or `categorize_claim` job; missing key completes the job without applying. Claim-only rows are provisional Apple Wallet Real-time Claims that are not yet linked to a Transaction.
