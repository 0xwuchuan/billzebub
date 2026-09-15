# NAS deployment and recovery

This is the production statement-and-Apple-Wallet release path. It uses only host-local Docker ports and Tailscale Serve; the API, PostgreSQL, artifacts, statement inbox, backups, and secrets are never public internet services.

## What is deployed

`compose.nas.yaml` builds one immutable application image and runs:

- `postgres`, without a published host port;
- `api`, published only at `127.0.0.1:8000` and serving the built SPA on the same origin;
- `worker`, which owns statement-inbox polling; and
- a profile-gated `migrate` maintenance container. It is never started during ordinary service startup.

The app services run as UID/GID `10001`, have read-only root filesystems, no Linux capabilities, bounded tmpfs space, health checks, memory limits, and locally rotated Docker logs. PostgreSQL retains its required writable data directory but has no exposed port. PostgreSQL and the worker are confined to an internal Compose network; the API also joins a dedicated proxy network solely so Docker can publish its loopback-only host port.

## Host preparation

Because this repository has no initial Git commit, run `scripts/nas/publish-source.sh` from the Mac checkout first. It archives only Git-visible, non-ignored source files into a temporary NAS directory and swaps the application directory only after validation; `.tmp`, artifacts, fixtures, databases, captures, and secrets cannot be transferred by it.

Then run `scripts/nas/cutover-wizard.sh` from the NAS checkout to walk through the guarded owner actions, or run `scripts/nas/bootstrap.sh` as root once when following the commands manually. It creates private runtime directories, an initial PostgreSQL password, a private database-URL file, and the non-secret runtime configuration. It requires these environment values before it will act:

- `BILLZEBUB_TAILSCALE_ALLOWED_LOGINS`: a JSON allowlist containing the owner Tailnet login;
- `BILLZEBUB_APPLE_WALLET_TIMEZONE`: the owner's IANA timezone.

The bootstrap script generates secrets locally, prints neither their values nor their filenames, and refuses to replace an existing runtime configuration or database secret. The application reads its database URL only from the mounted private file in NAS mode.

The statement inbox host path is `/volume1/billzebub-inbox` (a Synology Shared Folder; DSM share names are effectively case-folded) and is owned by the worker UID. Grant the NAS account that drops statements only the narrow write access needed for that folder; do not widen artifact or secret access. The container mount target remains `/var/lib/billzebub/inbox`. Statement-password and Apple-card-label files must be regular mode-`0600` files readable by UID `10001` inside the mounted secret directory.

## First deployment and upgrades

After host preparation, run `scripts/nas/deploy-initial.sh` from the checkout. It builds the image, starts PostgreSQL, runs the explicit migration container, starts API and worker, and waits for `/health/ready`.

For every later release, run `scripts/nas/upgrade.sh` instead. It:

1. stops API and worker writers;
2. creates and verifies a private logical PostgreSQL backup;
3. rebuilds the application image;
4. applies migrations explicitly; and
5. restarts API and worker only after the migration succeeds and then checks readiness.

Ordinary `docker compose up` must not be used as a substitute for the upgrade script because it intentionally does not migrate.

## Tailscale and owner browser access

Once a local readiness check succeeds, run:

```bash
scripts/nas/enable-tailscale-serve.sh --replace-probe
```

This deliberately replaces the temporary probe's Serve configuration with the production API. Run it only after the production endpoint has been tested locally. Uvicorn trusts forwarded scheme headers only in NAS mode, where Compose publishes the API solely on host loopback and Tailscale Serve is the proxy.

## Apple Wallet cutover

Do not stop the probe yet. For an interactive one-card setup that keeps the statement identifier and Wallet label on the NAS, run `scripts/nas/setup-apple-wallet-card.sh` from the NAS checkout. It creates the Financial Account and alias, reveals a one-time scoped Shortcut token for direct pasting, optionally imports retained probe captures, and guides the real-event and recovery checks.

1. Create Financial Account card aliases from private mode-`0600` label files with the `billzebub account apple-wallet-alias` command in the maintenance container.
2. Issue a fresh `integration` token scoped only to `shortcut:claims:create`; copy it directly into the Shortcut Authorization header and do not retain it in a shell history or Git file.
3. Update the Shortcut endpoint URL to `/api/v1/ingestions/apple-wallet`. Existing `probe-2` Wallet bodies stay valid; new Wallet and PayLah Shortcuts should send `realtime-1` JSON with an explicit `source`.
4. Import retained probe bodies through the maintenance container. It has a read-only mount of only the probe `captures` directory and joins its dedicated read-only group; it never receives the probe bearer token.
5. Make one normal Apple Pay purchase, verify the new endpoint creates one provisional Claim, then wait for the next card statement and verify reconciliation.
6. Only after successful production capture and backfill, stop and remove the throwaway probe. Its old raw bodies must already be retained in the Billzebub Source Artifact store.

The production endpoint records exact bodies, maps Wallet instruments only through local aliases, routes PayLah events to the single active `paylah` Financial Account, uses the mapped Financial Account's currency for dollar-prefixed source text, and applies the configured owner timezone to the local Shortcut timestamp. Unknown Wallet instruments and a missing or ambiguous PayLah account remain blocking review conditions and create no Claim. Invalid Shortcut JSON opens an Attention Review. `source` values `apple-pay`, `apple_pay`, and `Apple Pay` normalize to `apple_wallet`.

After this parser upgrade, reprocess only the failed `apple_wallet_shortcut` Extractions you name. In the maintenance container, pass tonight’s two `unsupported_source` Extraction ids (or their Source Artifact ids):

```bash
billzebub apple-wallet reprocess --extraction-id <extraction-id> --extraction-id <extraction-id>
```

Do not bulk-reprocess the historical `invalid_payload_*` pile. The command re-reads stored artifact bytes through ingest, is idempotent, and does not print payload bytes.

## Backup and restore

Schedule `scripts/nas/backup.sh` once daily with Synology Task Scheduler. It uses `pg_dump` inside the PostgreSQL container, verifies the custom-format dump with `pg_restore --list`, stores it privately, and retains 30 days. Do not back up the live PostgreSQL data directory as the restore strategy.

Run `scripts/nas/restore-drill.sh` after the first backup and periodically thereafter. It restores the newest dump into an isolated, network-disabled disposable PostgreSQL container and verifies the Alembic history without printing private database contents.

Configure Synology Hyper Backup to back up the private artifact store, logical backup directory, and secret directory. Its destination and encryption configuration are owner-controlled and outside this repository.
