# Billzebub v1 implementation plan

## Outcome

V1 builds a trustworthy, local expense history from DBS, Citi, and UOB credit-card statements, Apple Wallet events, and PayLah email. It preserves every Source Artifact and Claim, confirms Transactions from validated statement evidence, reconciles Real-time Claims when evidence is strong, exposes constrained operations to an external personal agent, and presents a minimal Copilot-inspired Flexoki Dark web UI.

V1 is complete only when all three credit-card formats and PayLah work end to end. Deposit-account statements, account-balance reporting, and cross-account Transfer consolidation are post-v1.

## Fixed constraints

- Monetary values are exact decimals with explicit currencies; no floating-point value crosses an ingestion seam.
- A failed statement Extraction creates no Claims.
- Source Artifacts, Claims, Corrections, and ledger entries are never overwritten or hard-deleted.
- Only confirmed Transactions enter the ledger. Provisional and Unconfirmed Claims affect estimated views only.
- Statement balances validate Extractions but do not create Opening Balance entries or balance dashboards.
- Card payments and PayLah funding are Transfers even when only one side is available.
- Raw financial data stays local. External agents receive only the agent-safe representation from ADR 0003.
- The browser is available only through Tailscale Serve and an allowlisted Tailscale identity.
- Statement and mailbox credentials are host-managed secret files, not database values.

## Architectural shape

Use a PostgreSQL-backed Python modular monolith:

```text
Browser ──Tailscale Serve──> FastAPI process ──> PostgreSQL
                                  │
                                  └── serves compiled React SPA

Watched folders ───────────> Worker process ──> artifact store + PostgreSQL
PayLah IMAP ───────────────> Worker process
Apple Shortcut ────────────> FastAPI ingestion endpoint

External agent ──stdio MCP adapter──> agent-safe HTTPS resources
```

Production has three long-running containers: `api`, `worker`, and `postgres`. The API and worker use the same Python package. Tailscale remains on the NAS host. No Redis, Celery, embedded agent, Telegram bot, or remotely exposed MCP process is added.

Recommended implementation stack:

- Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, and psycopg 3.
- PostgreSQL 16 or newer.
- React, TypeScript, Vite, React Router, TanStack Query, and accessible headless UI primitives.
- Tailwind CSS or plain tokenized CSS using the fixed Flexoki palette; self-host Inter.
- pytest for Python, Vitest for frontend logic, and Playwright for user workflows.
- `uv` for Python dependency locking and `pnpm` for frontend dependencies.

## Deep modules and seams

Avoid a generic layer or repository per database table. Introduce a seam only where behaviour genuinely varies or where it hides substantial policy.

### Artifact capture module

**Interface:** capture a file, HTTP body, or email message and return an immutable `SourceArtifactRef`.

The implementation owns stable-file detection, size limits, SHA-256 addressing, atomic copy and verification, duplicate arrivals, original metadata, and safe content paths. Callers never construct artifact paths.

Adapters: watched-folder file, Apple HTTP body, and RFC 822 email.

### Statement extraction module

**Interface:** extract one Source Artifact for one expected Financial Account and return either a complete validated candidate set or a structured failure.

The implementation hides PDF decryption, Monopoly, raw-text recovery, Decimal conversion, row coverage, account and statement-period checks, duplicate detection, totals or balance validation, and page/text provenance. DBS, Citi, and UOB are real adapters at this seam.

No caller can persist individual rows. Acceptance persists the Extraction and all Claims in one PostgreSQL transaction.

### Reconciliation module

**Interface:** evaluate eligible Claims and return explicit confirmation, ambiguity, rejection, or no-match outcomes with auditable evidence.

The implementation owns candidate generation, deterministic scoring, one-to-one use of Claims, Counterparty comparison, date windows, FX compatibility, the 14-day posting allowance, score threshold and runner-up margin, and prior rejected pairings. Callers do not manipulate scores.

### Financial history module

**Interface:** confirm a Transaction or apply an accepted Correction and return the new effective version.

The implementation atomically maintains Transaction versions, Claim links, Transaction Kind, Category Splits, Offset Allocations, append-only journals and postings, reversals, and current projections. It guarantees balanced postings and prevents over-allocation.

### Review inbox module

**Interface:** synchronize a review condition or apply one permitted decision.

The implementation owns active-review uniqueness, Attention versus Blocking severity, versions, automatic resolution, cancellation when conditions disappear, and immutable decision history.

### Agent facade module

**Interface:** return agent-safe resources and accept only scoped categorization or proposal commands.

This module is the sole seam crossed by MCP. It prevents accidental exposure of Financial Account identifiers, raw descriptions, Claims, Source Artifacts, statement locations, credentials, and audit internals.

### Durable job module

**Interface:** enqueue idempotently, lease due work, complete it, or record a retry/final failure.

The PostgreSQL implementation uses leases and `FOR UPDATE SKIP LOCKED`; it provides crash recovery without exposing queue mechanics to ingestion modules. Transient I/O failures retry with bounded exponential backoff. Deterministic parser or validation failures do not loop.

## Persistence groups and invariants

Finalize exact columns during migrations, but preserve these record groups:

1. **Configuration** — Financial Accounts, local aliases, institution and format, watched-folder key, and secret reference names.
2. **Evidence** — Source Artifacts, duplicate arrivals, Extractions, validation reports, immutable Claims, source locators, and Claim disposition events.
3. **History** — Transactions, effective versions, Reconciliations, rejected pairings, Corrections, Category Splits, and Offset Allocations.
4. **Ledger** — internal ledger accounts, append-only journals, postings, reversals, and current reporting projections. No opening-balance projection in v1.
5. **Workflow** — Pending Reviews, review events and decisions, durable jobs, and import/reprocess requests.
6. **Access and safety** — hashed scoped tokens, idempotency records, Tailscale owner allowlist, audit actors, and security events.
7. **Reference data** — Category hierarchy and locally cached complete daily FX tables.

Use UUIDv7 primary identifiers, PostgreSQL `numeric` for money, ISO currency codes, RFC 3339 instants, and explicit calendar dates. Current-state columns or projection tables may be updated transactionally for query speed, but immutable event records remain authoritative for audit.

## Delivery phases

### Phase 0 — Safety and repository bootstrap

**Status: complete.**

- Add root ignores for `fixtures/private/`, probe runtime data, `.env` files, secret directories, PDFs, `.eml` files, PostgreSQL data, dumps, and generated logs.
- Add a secret-scanning check and a test that fails if private-fixture paths become tracked.
- Create the Python and frontend workspaces, locked dependencies, formatting, linting, type checking, and test commands.
- Add a development Compose file with PostgreSQL only; application processes may run directly during development.
- Add synthetic, non-financial committed fixtures for all early tests.
- Keep the NAS Apple probe running until Phase 8 replaces it.

**Exit:** a clean checkout can run lint, type checks, unit tests, and a PostgreSQL integration test without any private data.

### Phase 1 — Runtime, configuration, and persistence foundation

**Status: complete.**

- Add typed configuration with separate development, test, and NAS deployment modes.
- Implement migrations for Financial Accounts, Categories, audit actors, tokens, idempotency, durable jobs, and the evidence/history skeleton.
- Implement an exact `Money` value type that refuses floats at construction and JSON seams.
- Implement the artifact capture module and a temporary-directory adapter for tests.
- Implement the PostgreSQL durable job module and worker loop.
- Add `/health/live` and `/health/ready` resources.
- Implement Tailscale identity verification: accept only configured logins, trust headers only behind the localhost Serve path, and provide an explicit localhost-only development identity mode.
- Implement hashed, scoped bearer-token creation, rotation, revocation, and last-used tracking.

**Exit:** API and worker survive restart, jobs resume after a killed worker, duplicate artifact capture is idempotent, and unauthorized identities or scopes fail closed.

### Phase 2 — Financial history core using synthetic Claims

**Status: complete.**

- Implement Claim content and append-only disposition events: Provisional, Confirmed, Unconfirmed, and Excluded.
- Implement Transaction Kind and effective-date precedence.
- Implement Transaction confirmation, Corrections, Category hierarchy, Uncategorized, Category Splits, and Offset Allocations.
- Implement append-only journal/posting generation and reversal/replacement behaviour.
- Treat Income as preserved but uncategorized; treat card payments and funding as one-sided Transfers against a hidden internal counterpart.
- Implement Review inbox lifecycle and active-review uniqueness.
- Build deterministic synthetic scenarios for purchases, statement-only purchases, transfers, partial refunds, aggregate reimbursements, cash withdrawals, Category changes, splits, and financial-fact Corrections.

**Exit:** property tests prove every journal balances, allocations cannot exceed either side, no provisional Claim reaches the ledger, and every effective change retains its prior history.

### Phase 3 — Shared statement ingestion and strict Extraction

**Status: complete.**

- Create the NAS inbox contract and account-specific folder configuration.
- Poll folders rather than relying on filesystem notifications; require stable size and modification time before capture.
- Move a verified copy into the content-addressed artifact store before removing the inbox file.
- Add PDF password lookup through mounted secret references.
- Define the statement adapter result with raw Decimal strings, dates, descriptions, statement identity, period, currencies, totals, and page/text locators.
- Publish Monopoly only behind the adapter. Reject a float result at the seam; recover monetary strings before conversion.
- Stage complete results in memory, run all validation, then atomically persist accepted Extraction and Claims.
- Persist structured sanitized failure reports and create one Blocking Pending Review on failure.
- Reprocess failed Extractions automatically only after an adapter version change. Require an explicit diff for successful reprocessing.
- Build Imports resources before the polished UI so failures can be inspected through OpenAPI.

**Exit:** synthetic PDFs prove all-or-nothing acceptance, account mismatch rejection, duplicate idempotency, row-coverage checks, exact decimals, provenance, parser-version tracking, and crash recovery.

### Phase 4 — DBS, Citi, and UOB credit-card adapters

**Status: complete.** DBS, Citi, and UOB passed the shared synthetic atomic-Extraction suite and three consecutive private statement periods locally. UOB's consolidated statements were validated independently for each of two card sections. No accepted private sample contained original-currency transaction evidence.

Implement the adapters sequentially against one shared acceptance suite; do not fork workflow behaviour per institution.

For each institution:

1. Begin with one private statement to establish the format.
2. Add three consecutive statements before accepting the adapter.
3. Store PDFs and expected normalized output only under `fixtures/private/`.
4. Add sanitized synthetic regressions for every parser bug that can be reproduced without personal data.
5. Exercise card payments, Refunds, FX lines, repeated purchases, long descriptions, page transitions, credits, fees, and missing/changed templates when examples exist.
6. Record Monopoly version plus Billzebub adapter version in every Extraction.

Use statement original-currency evidence where present. Cache a complete official daily FX table locally; initially allow a ±10% reference-rate band only when currencies differ and the other match evidence is strong. Missing reference data prevents FX auto-confirmation but not statement-only Transaction establishment.

**Exit:** all three adapters pass the same strict contract over at least three consecutive private statements each, with no skipped candidate rows and no committed personal data.

### Phase 5 — Reconciliation and confirmation pipeline

**Status: complete.** Reconciliation is a single transactional module with account-level job serialization. It records accepted and rejected Claim pairings append-only, auto-confirms only mutual high-confidence matches, and creates versioned Claim-scoped Reviews for ambiguity or aged unmatched Real-time Claims. The initial deterministic calibration uses a seven-day activity-date window, an 80-point automatic threshold, and a 15-point runner-up margin. Exact same-currency/original-currency evidence is preferred; cross-currency auto-confirmation requires an official local reference rate within a ±10% band and otherwise safely falls back to Statement-only establishment.

- Generate candidates only within the same Financial Account and eligible date window.
- Score amount compatibility, dates, deterministic Counterparty similarity, and uniqueness; retain a complete reason list.
- Confirm only above a calibrated threshold and runner-up margin. Use private fixtures to tune false-review and false-match rates without adding a learned model.
- Establish statement-only Transactions automatically.
- Keep unmatched Real-time Claims Provisional until accepted statement history ends at least 14 days after occurrence; then move them to Unconfirmed and create Attention review.
- Let later evidence move Unconfirmed to Confirmed while preserving disposition history.
- Persist rejected pairings so they are not proposed repeatedly.
- Rank ambiguous candidates in one versioned Pending Review with explicit decisions.
- Ensure confirmation and ledger posting are one database transaction.

**Exit:** scenario tests cover exact SGD, plausible FX, same-merchant ambiguity, repeated equal amounts, cutoff dates, late posting, rejected pairs, statement-only activity, and race-safe repeated jobs.

### Phase 6 — Versioned HTTP resources, agent facade, and MCP

**Status: in progress.** The versioned agent-safe Transaction, Category, and Review resources; structured problem responses; ETags; cursor pagination; replay-safe categorization; proposal-backed Reviews; and the local eight-tool MCP adapter are implemented and covered by HTTP/facade/MCP contracts. The owner CLI now bootstraps a validated statement-backed Financial Account and its isolated inbox after a non-mutating dry run. Owner Transaction and Pending Review projections now support cursor navigation, ETags, audited categorization, and only workflow-owned Review decisions; browser mutations enforce same-origin, JSON-only, SPA-header-protected mutation. The broader owner-browser resource set remains pending.

- Publish `/api/v1` REST JSON resources and generated OpenAPI.
- Serialize monetary decimals as strings and errors as structured problem documents.
- Add cursor pagination, ETags/resource versions, and required idempotency keys for ingestion and agent mutations.
- Add browser resources for Overview, Transactions, Reviews, Imports, Financial Accounts, Categories, tokens, Corrections, splits, allocations, and reprocessing. Require same-origin checks, JSON-only mutations, and an SPA-specific anti-CSRF header even though browser identity comes from Tailscale.
- Add a separately projected `/api/v1/agent` surface containing only the accepted agent-safe fields.
- Implement scopes for Shortcut ingestion, agent reads, categorization, and proposals.
- Implement categorization as an audited reclassification that automatically resolves the current categorization Review.
- Implement proposal-backed Pending Reviews for Corrections, Reconciliation, Counterparty changes, and Category Splits.
- Build the stateless Python stdio MCP adapter with only the eight accepted explicit tools.
- Add contract tests proving every agent/MCP response excludes forbidden fields recursively.

**Exit:** an external test agent can categorize an obvious Transaction and propose an ambiguous decision but cannot obtain Source Artifacts, Claims, account identifiers, or silently change financial facts.

### Phase 7 — Responsive Flexoki Dark web UI

**Status: in progress.** The responsive Flexoki Dark workspace now loads current Transactions and Pending Reviews from the owner HTTP resources, supports cursor navigation, owner-audited categorization, and permitted Review decisions. Overview, Imports, Settings, transaction detail, and advanced workflows remain pending.

Build one responsive SPA using the HTTP resources rather than bypassing them.

- **Overview:** confirmed, provisional, and estimated current-month spending; category ring and exact ranked list; Pending Review and failed Extraction counts; drill-down links.
- **Transactions:** search, cursor navigation, account/category/Counterparty/date/confirmation/review filters, compact rows, and provisional/confirmed labels.
- **Transaction drawer:** effective facts, Category action, advanced splits, offset links, Corrections, linked Claims, source provenance, and audit history. Keep accounting terminology behind a technical-detail disclosure.
- **Review:** grouped Blocking and Attention queues, permitted decisions, safe bulk categorization, and stale-version handling.
- **Imports:** Source Artifact and Extraction status, parser versions, periods, validation reports, duplicate arrivals, diffs, and retry/reprocess actions.
- **Settings:** Financial Accounts, aliases, watched-folder status, Categories, Tailscale owner status, configured/not-configured secret status, and integration-token lifecycle.

Apply the confirmed Flexoki tokens, Inter tabular numerals, Copilot-like mixed density, left desktop navigation, compact mobile top navigation, side drawers, and one restrained category ring. Self-host all assets, add no telemetry, and never use color alone for state.

**Exit:** Playwright covers the primary mobile and desktop workflows, keyboard navigation, drill-down consistency, stale mutations, and absence of forbidden raw data in agent-oriented views.

### Phase 8 — Replace the Apple Wallet probe with production ingestion

This phase begins only after an ordinary physical Apple Pay purchase reaches the NAS probe.

**Implementation status:** the observed `probe-2` Shortcut contract is implemented behind the scoped production endpoint. It retains exact request bodies, accepts a private local card-label alias, parses the observed dollar-prefixed amount and local abbreviated-month date strictly, uses the mapped Financial Account's currency and configured IANA timezone, and fails closed. NAS deployment, probe-artifact backfill, token rotation, and a real statement reconciliation remain outstanding.

- Inspect exact fields and types locally without committing the capture.
- Determine whether Name, Card, Merchant, Amount, currency, and Current Date are reliable and whether whole-input text adds value.
- Reduce the Shortcut to one production request; remove exploratory duplicate requests.
- Define a versioned payload and retain its exact body as a Source Artifact.
- Use an explicit event identifier if iOS exposes one. Otherwise deduplicate exact retry bodies by artifact hash while allowing distinct purchases with different captured timestamps.
- Map Wallet card labels through local Financial Account aliases; unknown cards create Blocking review and no Claim.
- Create a Provisional Real-time Claim with Authorized Amount and occurrence time.
- Preserve incomplete transit/pass events but mark them Excluded from Reconciliation.
- Test locked-phone execution, repeated delivery, unavailable Tailscale, receiver restart, non-payment passes, FX, and missing amounts through normal usage.
- Import every real probe capture into the production content-addressed Source Artifact store, verify its hash, and retain it indefinitely. Replace the probe route with the production endpoint, rotate its token, verify one real reconciliation against a card statement, then remove the probe container; only explicitly identified synthetic connectivity probes may be discarded.

**Exit:** a real Wallet event creates exactly one eligible Real-time Claim, survives API/worker restart, and either confirms against a Statement Claim or follows the documented Unconfirmed path.

### Phase 9 — PayLah email

Run a private spike before fixing the production contract.

- Collect a small local set of raw `.eml` messages covering merchant payments, funding, Refunds, failures, and template variants when naturally available.
- Connect read-only to a dedicated mailbox or folder using a mounted app-password secret.
- Capture complete RFC 822 messages before parsing; never mutate read/unread state or delete/move messages.
- Deduplicate with UIDVALIDITY, UID, Message-ID, and content hash.
- Validate expected sender, recipient, subject family, recognized template, and available SPF/DKIM results.
- Parse known templates into Provisional Claims; unknown templates create no Claim and one Blocking review.
- Classify funding as Transfer and merchant payment as Expense. Avoid double counting linked-account funding without requiring deposit statements.
- Add sanitized synthetic message fixtures and keep every real `.eml` private.

**Exit:** naturally observed PayLah message types ingest automatically and idempotently, unknown templates fail closed, mailbox credentials never enter PostgreSQL, and no mailbox state is changed.

### Phase 10 — NAS release, backup, and backfill

**Implementation status:** production Compose, image build, same-origin static SPA serving, host-managed database-secret support, explicit deploy/upgrade, backup, restore-drill, Tailscale cutover, and Apple probe-import scripts are in the repository. The NAS host setup, first production deployment, owner secret/token configuration, probe backfill, and restore drill remain operator actions.

- Create `/volume1/Billzebub-Inbox/` with DBS, Citi, and UOB account folders and least-privilege worker access.
- Create private `/volume1/docker/billzebub/{artifacts,postgres,backups,secrets}` paths with documented ownership and modes.
- Build production images with pinned dependencies, non-root users, read-only filesystems where practical, health checks, resource limits, and rotated logs.
- Bind API only to localhost and replace the probe's Tailscale Serve route with Billzebub HTTPS.
- Add an explicit upgrade command: stop writers, create `pg_dump`, apply Alembic migrations, start containers, and verify readiness. Ordinary startup never migrates.
- Add nightly logical dumps and a restore drill into a disposable PostgreSQL instance.
- Configure Synology Hyper Backup for artifacts, dumps, and secrets; do not back up the live PostgreSQL directory as the database restore strategy.
- Verify redaction, 30-day container-log retention, health reporting, worker restart, expired job leases, token rotation, and “log out” equivalent by revoking Tailnet/browser access or integration tokens.
- Import three months for all three card institutions, inspect every Blocking review, and compare sampled statement totals and category reports manually.

**Exit:** restore succeeds from documented backups, all source formats pass on the NAS, no container requires the Mac, and the v1 definition of done below is met.

## V1 definition of done

- Three consecutive private statements each for DBS, Citi, and UOB pass strict, atomic Extraction.
- Statement-only activity establishes Transactions without unnecessary review.
- Strong Real-time/Statement matches confirm automatically; ambiguous and late cases follow the accepted review lifecycle.
- Confirmed spending, provisional estimates, Refund/Reimbursement offsets, Transfers, Category Splits, and Corrections produce exact and balanced results.
- The external agent can categorize safely through HTTP or MCP without receiving forbidden information.
- Overview, Transactions, Review, Imports, and Settings work responsively in Flexoki Dark.
- Apple Wallet and PayLah produce automatic Provisional Claims from at least one real supported event/template each.
- Deposit-account statements, balances, and transfer-side consolidation are absent and explicitly documented as post-v1.
- PostgreSQL, Source Artifacts, and secrets can be restored from the NAS backup procedure.
- No real PDF, `.eml`, captured Wallet body, credential, account identifier, or database dump is tracked by Git or emitted to application logs.

## Empirical gates, not unresolved product decisions

1. **Monopoly adapter gate:** verify each adapter can recover exact monetary strings, complete row coverage, and page/text provenance. If the published interface cannot, add a narrowly scoped Billzebub adapter extension or upstream contribution rather than weakening validation.
2. **Apple gate:** observe one real Wallet event before finalizing payload and idempotency.
3. **PayLah gate:** inspect real local `.eml` structures before finalizing templates and IMAP queries.
4. **FX calibration gate:** tune the accepted initial ±10% band and score margin using private fixtures; never optimize solely for fewer Reviews at the cost of false confirmation.

These gates may change adapters and thresholds, but not the established Source Artifact → Extraction → Claim → Reconciliation → Transaction model.
