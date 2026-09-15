# Billzebub

Billzebub is a local-first personal expense tracker that builds trusted Transactions from immutable real-time and statement Claims. See [`CONTEXT.md`](CONTEXT.md) for domain language and [`docs/v1-implementation-plan.md`](docs/v1-implementation-plan.md) for the accepted v1 plan.

## Development prerequisites

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node.js 22+ and pnpm 10
- Docker Compose for PostgreSQL integration tests
- Poppler C++ headers, `pkg-config`, and a C++ compiler for Monopoly's PDF text bridge

## Set up

```bash
uv sync --locked --all-groups
pnpm install --frozen-lockfile
```

## Checks

```bash
make check              # formatting, lint, types, tests, build, and safety checks
make postgres-up        # requires Docker
make test-integration   # uses the development PostgreSQL container
make postgres-down
```

Start the development runtime after PostgreSQL is healthy:

```bash
make postgres-up
make migrate              # explicit; ordinary startup never migrates
make api                  # http://127.0.0.1:8000
make worker
pnpm --dir web dev
```

The API exposes `/health/live`, `/health/ready`, authenticated `/api/v1/imports` diagnostics, owner `/api/v1/transactions` and `/api/v1/reviews` workspace resources, `/api/v1/agent` resources, and a development-only `/api/v1/whoami` resource. The bearer-protected `POST /api/v1/ingestions/apple-wallet` endpoint retains exact Shortcut JSON bodies and creates fail-closed Real-time Claims for Apple Wallet and PayLah. Owner mutations require same-origin JSON plus the `X-Billzebub-CSRF: bzb-spa` header and a current ETag. `make api` supplies a loopback-only development identity; NAS mode instead requires an allowlisted Tailscale identity.

Configuration uses `BILLZEBUB_` environment variables and is not loaded automatically from `.env` files. Important settings are `ENVIRONMENT`, `DATABASE_URL`, `ARTIFACT_ROOT`, `STATEMENT_INBOX_ROOT`, `STATEMENT_PASSWORD_ROOT`, `STATEMENT_STABLE_SECONDS`, `APPLE_WALLET_TIMEZONE`, `TRUST_TAILSCALE_HEADERS`, `TAILSCALE_ALLOWED_LOGINS` (a JSON list), and `DEVELOPMENT_IDENTITY`.

The worker polls one folder per configured Financial Account:

```text
$BILLZEBUB_STATEMENT_INBOX_ROOT/<financial-account-slug>/*.pdf
```

A file must retain the same size and modification time across the stability interval before capture. The worker verifies a content-addressed copy, enqueues Extraction, and only then removes the inbox file. Optional PDF passwords are permission-restricted files under `STATEMENT_PASSWORD_ROOT`; PostgreSQL stores only the configured secret filename. The accepted credit-card adapters are `dbs-credit-card`, `citi-credit-card`, and `uob-credit-card`.

Create each statement-backed Financial Account explicitly. Store its statement selector in an uncommitted, `0600` local file; the CLI never prints its value or filename. Use `--dry-run` first, then repeat without it to create the database record and an empty `0700` inbox folder:

```bash
chmod 600 /private/path/statement-account-selector
uv run billzebub account bootstrap \
  --slug dbs-primary-card \
  --display-name "Primary card" \
  --institution dbs \
  --currency SGD \
  --statement-adapter dbs-credit-card \
  --statement-account-identifier-file /private/path/statement-account-selector \
  --dry-run
```

Do not place selectors, statement passwords, or their paths in Git, shell history, or chat. When a statement needs a password, create its named `0600` secret under `STATEMENT_PASSWORD_ROOT` and pass only `--statement-password-secret <reference>`.

Administrative commands are explicit:

```bash
uv run billzebub check
uv run billzebub migrate
uv run billzebub token issue --name "Apple Shortcut" \
  --kind integration --scope shortcut:claims:create
uv run billzebub token rotate <token-id>
uv run billzebub token revoke <token-id>
```

Token plaintext is displayed only by `token issue`; PostgreSQL stores its SHA-256 digest and scoped metadata.

### Shortcut Real-time Claim setup

Apple Wallet and PayLah Shortcuts share `POST /api/v1/ingestions/apple-wallet` and the `shortcut:claims:create` bearer token. Set `BILLZEBUB_APPLE_WALLET_TIMEZONE` to the owner's IANA timezone. Amounts must be `$`-prefixed text and dates must be local English text such as `7 Mar 2026 at 9:05 PM`. Currency comes from the resolved Financial Account. Unknown `schema_version` or `source` values fail closed.

Legacy `probe-2` Wallet bodies remain valid and must not include `source`:

```json
{
  "schema_version": "probe-2",
  "name": "Synthetic name",
  "merchant": "Synthetic merchant",
  "card": "Synthetic Wallet Card",
  "amount": "$12.34",
  "date": "7 Mar 2026 at 9:05 PM"
}
```

New captures use `realtime-1` with an explicit `source`. Wallet events map `instrument` (or the deprecated `card` alias) through the same private card-label aliases as `probe-2`:

```json
{
  "schema_version": "realtime-1",
  "source": "apple_wallet",
  "name": "Synthetic name",
  "merchant": "Synthetic merchant",
  "instrument": "Synthetic Wallet Card",
  "amount": "$12.34",
  "date": "7 Mar 2026 at 9:05 PM"
}
```

PayLah events accept only `name`, `amount`, and `date`. Extra `merchant`, `card`, or `instrument` fields are rejected. The Claim is routed to the single active Financial Account of kind `paylah`; zero or multiple active PayLah accounts fail closed:

```json
{
  "schema_version": "realtime-1",
  "source": "paylah",
  "name": "Synthetic PayLah name",
  "amount": "$8.50",
  "date": "7 Mar 2026 at 9:05 PM"
}
```

Create a mode-`0600` local file containing the Wallet card label, then configure it without printing its contents:

```bash
uv run billzebub account apple-wallet-alias \
  --slug <account-slug> --card-label-file /private/path/wallet-card-label
```

Issue an `integration` token with `shortcut:claims:create`, put it only in the Shortcut Authorization header, and send JSON to `/api/v1/ingestions/apple-wallet`. Exact replay bodies share one Source Artifact and one Claim. Unknown Wallet instruments create a Blocking Review and no Claim. Card labels match after NFKC, folding typographic apostrophes to ASCII `'`, collapsing whitespace (including trailing newlines), and casefolding; genuinely different names still fail closed. Invalid Shortcut JSON creates an Attention Review (`shortcut_payload_invalid`) and no Claim.

Wallet `realtime-1` also accepts `source` aliases `apple-pay`, `apple_pay`, and `Apple Pay`, which normalize to `apple_wallet` before field checks. After deploy, re-ingest stored failed `apple_wallet_shortcut` Extractions by id without changing the Shortcut:

```bash
uv run billzebub apple-wallet reprocess --extraction-id <extraction-id>
uv run billzebub apple-wallet reprocess --artifact-id <source-artifact-id>
```

Pass tonight’s two `unsupported_source` Extraction ids only. The command re-reads stored artifact bytes through ingest, is idempotent, and never prints payload bytes.

## Local MCP adapter

`billzebub-mcp` is a local stdio process, never a network service. Configure it with `BILLZEBUB_API_URL` (HTTPS except on loopback) and `BILLZEBUB_AGENT_TOKEN`; do not put the token in an MCP configuration committed to Git. It exposes exactly eight agent-safe tools: transaction/category/review listing, explicit categorization, and owner-reviewed Correction, Reconciliation, Counterparty-change, and Category-split proposals. It cannot fetch Claims, artifacts, account identifiers, or audit details.

## NAS deployment

The production release uses [`compose.nas.yaml`](compose.nas.yaml) and explicit host setup, deploy/upgrade, backup, restore-drill, and Tailscale cutover scripts. Follow [`docs/nas-deployment.md`](docs/nas-deployment.md); it includes the Apple probe backfill sequence and never asks you to place secrets or captured data in the checkout.

## Private data

Real statements, Wallet and PayLah Shortcut captures, credentials, artifacts, database dumps, and expected outputs derived from real data must never be committed. Put private parser fixtures only under `fixtures/private/`; repository checks deliberately reject these file types even when force-added.

The current throwaway Apple Wallet spike is documented in [`prototypes/apple-shortcut-capture/README.md`](prototypes/apple-shortcut-capture/README.md). Its runtime data remains on the NAS and outside Git.
