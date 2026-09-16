"""Explicit administrative commands for migrations and integration tokens."""

from __future__ import annotations

import argparse
import stat
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config

from billzebub.apple_wallet import AppleWalletIngestion
from billzebub.apple_wallet_probe import AppleWalletProbeError, import_probe_captures
from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ArtifactStoreError, ContentAddressedStore
from billzebub.config import Settings
from billzebub.financial_account_aliases import FinancialAccountAliasError, FinancialAccountAliases
from billzebub.financial_accounts import (
    FinancialAccountBootstrap,
    FinancialAccountBootstrapCommand,
    FinancialAccountSetupError,
)
from billzebub.imports import (
    FailedImportPurgeReport,
    ImportCatalog,
    ImportNotDismissableError,
    ImportNotFoundError,
)
from billzebub.persistence.database import Database
from billzebub.persistence.models import AuditActorKind, FinancialAccountKind
from billzebub.tokens import TokenManager, TokenScope


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="billzebub")
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="apply versioned database migrations explicitly")
    commands.add_parser("check", help="verify database connectivity")

    account = commands.add_parser("account", help="bootstrap Financial Accounts explicitly")
    account_commands = account.add_subparsers(dest="account_command", required=True)
    bootstrap = account_commands.add_parser(
        "bootstrap",
        help="validate and create a statement-backed Financial Account",
    )
    bootstrap.add_argument("--slug", required=True)
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--institution", required=True)
    bootstrap.add_argument(
        "--kind",
        choices=[FinancialAccountKind.CREDIT_CARD.value],
        default=FinancialAccountKind.CREDIT_CARD.value,
    )
    bootstrap.add_argument("--currency", required=True)
    bootstrap.add_argument("--statement-adapter", required=True)
    bootstrap.add_argument("--statement-account-identifier-file", required=True, type=Path)
    bootstrap.add_argument("--statement-password-secret")
    bootstrap.add_argument("--dry-run", action="store_true")

    apple_wallet_alias = account_commands.add_parser(
        "apple-wallet-alias",
        help="map one private Apple Wallet card label to an active Financial Account",
    )
    apple_wallet_alias.add_argument("--slug", required=True)
    apple_wallet_alias.add_argument("--card-label-file", required=True, type=Path)

    imports = commands.add_parser("imports", help="operate owner Import history")
    imports_commands = imports.add_subparsers(dest="imports_command", required=True)
    dismiss = imports_commands.add_parser(
        "dismiss",
        help="soft-hide failed Extractions from the owner Imports list",
    )
    dismiss.add_argument(
        "--failed",
        action="store_true",
        help="dismiss every failed Extraction that is not already dismissed",
    )
    dismiss.add_argument("--extraction-id", type=UUID)
    purge_failed = imports_commands.add_parser(
        "purge-failed",
        help="hard-delete historical Shortcut/probe junk failed Extractions",
    )
    purge_failed.add_argument(
        "--dry-run",
        action="store_true",
        help="print matching rows without deleting (default when --execute is omitted)",
    )
    purge_failed.add_argument(
        "--execute",
        action="store_true",
        help="actually delete matching failed Extractions and orphan Source Artifacts",
    )
    purge_failed.add_argument(
        "--all-failed",
        action="store_true",
        help="include every failed Extraction, not only Shortcut/probe junk codes",
    )

    create_paylah = account_commands.add_parser(
        "create-paylah",
        help="create a Shortcut-backed PayLah Financial Account",
    )
    create_paylah.add_argument("--slug", required=True)
    create_paylah.add_argument("--display-name", required=True)
    create_paylah.add_argument("--institution", default="dbs")
    create_paylah.add_argument("--currency", default="SGD")

    apple_wallet = commands.add_parser(
        "apple-wallet", help="operate the local Apple Wallet ingestion"
    )
    apple_wallet_commands = apple_wallet.add_subparsers(dest="apple_wallet_command", required=True)
    import_probe = apple_wallet_commands.add_parser(
        "import-probe",
        help="copy private probe bodies into the production Source Artifact store",
    )
    import_probe.add_argument("--capture-root", required=True, type=Path)
    reprocess = apple_wallet_commands.add_parser(
        "reprocess",
        help="re-ingest stored failed apple_wallet_shortcut artifacts by id",
    )
    reprocess.add_argument("--extraction-id", action="append", default=[], type=UUID)
    reprocess.add_argument("--artifact-id", action="append", default=[], type=UUID)

    token = commands.add_parser("token", help="manage scoped integration tokens")
    token_commands = token.add_subparsers(dest="token_command", required=True)

    issue = token_commands.add_parser("issue", help="issue a token and reveal it once")
    issue.add_argument("--name", required=True)
    issue.add_argument(
        "--kind",
        required=True,
        choices=[AuditActorKind.AGENT.value, AuditActorKind.INTEGRATION.value],
    )
    issue.add_argument(
        "--scope",
        action="append",
        required=True,
        choices=[scope.value for scope in TokenScope],
    )

    rotate = token_commands.add_parser("rotate", help="atomically replace an active token")
    rotate.add_argument("token_id", type=UUID)

    revoke = token_commands.add_parser("revoke", help="revoke a token immediately")
    revoke.add_argument("token_id", type=UUID)
    return root


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parser().parse_args(argv)
    settings = Settings()

    if arguments.command == "migrate":
        command.upgrade(Config("alembic.ini"), "head")
        return

    database = Database(settings)
    try:
        if arguments.command == "check":
            database.ping()
            print("database connection ok")
            return
        if arguments.command == "account" and arguments.account_command == "bootstrap":
            try:
                identifier = _read_private_value(arguments.statement_account_identifier_file)
                result = FinancialAccountBootstrap(
                    database,
                    inbox_root=settings.statement_inbox_root,
                    password_root=settings.statement_password_root,
                ).bootstrap(
                    FinancialAccountBootstrapCommand(
                        slug=arguments.slug,
                        display_name=arguments.display_name,
                        institution=arguments.institution,
                        kind=FinancialAccountKind(arguments.kind),
                        default_currency=arguments.currency,
                        statement_adapter_key=arguments.statement_adapter,
                        statement_account_identifier=identifier,
                        statement_password_secret=arguments.statement_password_secret,
                    ),
                    dry_run=arguments.dry_run,
                )
            except (FinancialAccountSetupError, OSError, UnicodeError):
                raise SystemExit(
                    "Financial Account setup failed; inspect local configuration."
                ) from None
            if arguments.dry_run:
                del result
                print(
                    "Financial Account dry run passed; no database or filesystem changes were made."
                )
            else:
                print("Financial Account created and its statement inbox folder is ready.")
            return
        if arguments.command == "account" and arguments.account_command == "create-paylah":
            try:
                FinancialAccountBootstrap(
                    database,
                    inbox_root=settings.statement_inbox_root,
                    password_root=settings.statement_password_root,
                ).bootstrap(
                    FinancialAccountBootstrapCommand(
                        slug=arguments.slug,
                        display_name=arguments.display_name,
                        institution=arguments.institution,
                        kind=FinancialAccountKind.PAYLAH,
                        default_currency=arguments.currency,
                    )
                )
            except (FinancialAccountSetupError, OSError, UnicodeError):
                raise SystemExit(
                    "PayLah Financial Account setup failed; inspect local configuration."
                ) from None
            print(
                "PayLah Financial Account created. Shortcut ingest does not use a statement inbox."
            )
            return
        if arguments.command == "account" and arguments.account_command == "apple-wallet-alias":
            try:
                FinancialAccountAliases(database).add_apple_wallet_card(
                    account_slug=arguments.slug,
                    card_label=_read_private_value(arguments.card_label_file),
                )
            except (FinancialAccountAliasError, OSError, UnicodeError):
                raise SystemExit(
                    "Apple Wallet card alias setup failed; inspect local configuration."
                ) from None
            print("Apple Wallet card alias configured.")
            return
        if arguments.command == "imports" and arguments.imports_command == "dismiss":
            if arguments.failed == bool(arguments.extraction_id):
                raise SystemExit("specify exactly one of --failed or --extraction-id")
            catalog = ImportCatalog(database)
            try:
                if arguments.failed:
                    dismissed = catalog.dismiss_failed()
                    print(f"Dismissed {dismissed} failed Extraction(s).")
                    return
                record = catalog.dismiss(arguments.extraction_id)
            except ImportNotFoundError:
                raise SystemExit("Extraction was not found") from None
            except ImportNotDismissableError:
                raise SystemExit("Only failed Extractions may be dismissed") from None
            print(f"Dismissed Extraction {record.id}.")
            return
        if arguments.command == "imports" and arguments.imports_command == "purge-failed":
            if arguments.dry_run and arguments.execute:
                raise SystemExit("specify only one of --dry-run or --execute")
            report = ImportCatalog(database).purge_failed(
                dry_run=not arguments.execute,
                all_failed=arguments.all_failed,
            )
            _print_purge_report(report)
            return
        if arguments.command == "apple-wallet" and arguments.apple_wallet_command == "import-probe":
            if settings.apple_wallet_timezone is None:
                raise SystemExit("Apple Wallet ingestion is not configured.")
            try:
                import_probe_captures(
                    arguments.capture_root,
                    AppleWalletIngestion(
                        database,
                        ArtifactCapture(
                            ContentAddressedStore(
                                settings.artifact_root,
                                max_bytes=settings.artifact_max_bytes,
                            ),
                            database,
                        ),
                        FinancialAccountAliases(database),
                        timezone=ZoneInfo(settings.apple_wallet_timezone),
                    ),
                )
            except (AppleWalletProbeError, ArtifactStoreError, OSError, ValueError):
                raise SystemExit(
                    "Apple Wallet probe import failed; inspect local configuration."
                ) from None
            print("Apple Wallet probe import completed.")
            return
        if arguments.command == "apple-wallet" and arguments.apple_wallet_command == "reprocess":
            if settings.apple_wallet_timezone is None:
                raise SystemExit("Apple Wallet ingestion is not configured.")
            try:
                processed = AppleWalletIngestion(
                    database,
                    ArtifactCapture(
                        ContentAddressedStore(
                            settings.artifact_root,
                            max_bytes=settings.artifact_max_bytes,
                        ),
                        database,
                    ),
                    FinancialAccountAliases(database),
                    timezone=ZoneInfo(settings.apple_wallet_timezone),
                ).reprocess(
                    extraction_ids=tuple(arguments.extraction_id),
                    artifact_ids=tuple(arguments.artifact_id),
                )
            except (ArtifactStoreError, OSError, ValueError):
                raise SystemExit(
                    "Apple Wallet reprocess failed; inspect local configuration."
                ) from None
            print(f"Apple Wallet reprocess completed for {processed} Source Artifact(s).")
            return
        if arguments.command == "token" and arguments.token_command == "issue":
            manager = TokenManager(database)
            issued = manager.issue(
                name=arguments.name,
                actor_kind=AuditActorKind(arguments.kind),
                scopes=frozenset(TokenScope(scope) for scope in arguments.scope),
            )
            print(f"token_id={issued.id}")
            print(f"token={issued.plaintext}")
            print("This plaintext token will not be shown again.")
            return
        if arguments.command == "token" and arguments.token_command == "rotate":
            rotated = TokenManager(database).rotate(arguments.token_id)
            print(f"token_id={rotated.id}")
            print(f"token={rotated.plaintext}")
            print("The prior token is revoked; this plaintext token will not be shown again.")
            return
        if arguments.command == "token" and arguments.token_command == "revoke":
            if not TokenManager(database).revoke(arguments.token_id):
                raise SystemExit("token was not active or did not exist")
            print(f"revoked token {arguments.token_id}")
            return
        raise SystemExit("unsupported command")
    finally:
        database.close()


def _print_purge_report(report: FailedImportPurgeReport) -> None:
    action = "Would delete" if report.dry_run else "Deleted"
    print(
        f"{action} {len(report.extraction_ids)} failed Extraction(s) and "
        f"{len(report.artifact_ids)} orphan Source Artifact(s)."
    )
    if report.skipped_extraction_ids:
        print(
            f"Skipped {len(report.skipped_extraction_ids)} Extraction(s) with Claims "
            "or remaining dependents."
        )
    if report.dry_run and not report.extraction_ids and not report.skipped_extraction_ids:
        print("Nothing matched the junk filter.")
    elif report.dry_run:
        print("Dry run only; pass --execute to delete.")
    for extraction_id in report.extraction_ids:
        print(f"extraction_id={extraction_id}")
    for artifact_id in report.artifact_ids:
        print(f"artifact_id={artifact_id}")
    for extraction_id in report.skipped_extraction_ids:
        print(f"skipped_extraction_id={extraction_id}")


def _read_private_value(path: Path) -> str:
    """Read a local identifier without accepting a command-history or symlink leak."""
    expanded = path.expanduser()
    metadata = expanded.lstat()
    if not stat.S_ISREG(metadata.st_mode) or expanded.is_symlink() or metadata.st_mode & 0o077:
        raise OSError("private value file is unsafe")
    value = expanded.read_text(encoding="utf-8").strip()
    if not value or len(value) > 255:
        raise OSError("private value file is invalid")
    return value


if __name__ == "__main__":
    main()
