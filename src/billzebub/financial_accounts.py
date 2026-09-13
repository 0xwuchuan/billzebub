"""Owner-controlled Financial Account bootstrap and statement-inbox preparation."""

from __future__ import annotations

import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from billzebub.persistence.models import FinancialAccount, FinancialAccountKind

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_INSTITUTION_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_SECRET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class FinancialAccountSetupError(ValueError):
    """A requested Financial Account would violate the inbox setup contract."""


@dataclass(frozen=True, slots=True)
class FinancialAccountBootstrapCommand:
    slug: str
    display_name: str
    institution: str
    kind: FinancialAccountKind
    default_currency: str
    statement_adapter_key: str
    statement_account_identifier: str
    statement_password_secret: str | None = None


@dataclass(frozen=True, slots=True)
class FinancialAccountBootstrapPlan:
    slug: str
    institution: str
    kind: FinancialAccountKind
    default_currency: str
    statement_adapter_key: str
    password_configured: bool


@dataclass(frozen=True, slots=True)
class FinancialAccountRecord:
    id: UUID
    slug: str
    display_name: str
    institution: str
    kind: FinancialAccountKind
    default_currency: str
    statement_adapter_key: str
    active: bool


class FinancialAccountBootstrap:
    """Create one statement-backed Financial Account without accepting unsafe defaults."""

    def __init__(
        self,
        database: Database,
        *,
        inbox_root: Path,
        password_root: Path,
        adapters: Mapping[str, str] | None = None,
    ) -> None:
        self._database = database
        self._inbox_root = inbox_root.expanduser().resolve()
        self._password_root = password_root.expanduser().resolve()
        self._adapters = dict(adapters or self._configured_adapters())

    def plan(self, command: FinancialAccountBootstrapCommand) -> FinancialAccountBootstrapPlan:
        return self._plan(self._validate(command))

    def _plan(
        self,
        command: FinancialAccountBootstrapCommand,
    ) -> FinancialAccountBootstrapPlan:
        self._validate_password_secret(command.statement_password_secret)
        self._validate_inbox_target(command.slug)
        with self._database.transaction() as session:
            existing = session.scalar(
                select(FinancialAccount.id).where(FinancialAccount.slug == command.slug)
            )
            if existing is not None:
                raise FinancialAccountSetupError("Financial Account slug already exists")
        return FinancialAccountBootstrapPlan(
            slug=command.slug,
            institution=command.institution,
            kind=command.kind,
            default_currency=command.default_currency,
            statement_adapter_key=command.statement_adapter_key,
            password_configured=command.statement_password_secret is not None,
        )

    @overload
    def bootstrap(
        self,
        command: FinancialAccountBootstrapCommand,
        *,
        dry_run: Literal[True],
    ) -> FinancialAccountBootstrapPlan: ...

    @overload
    def bootstrap(
        self,
        command: FinancialAccountBootstrapCommand,
        *,
        dry_run: Literal[False] = False,
    ) -> FinancialAccountRecord: ...

    def bootstrap(
        self,
        command: FinancialAccountBootstrapCommand,
        *,
        dry_run: bool = False,
    ) -> FinancialAccountBootstrapPlan | FinancialAccountRecord:
        normalized = self._validate(command)
        plan = self._plan(normalized)
        if dry_run:
            return plan

        folder = self._inbox_root / plan.slug
        self._create_inbox_target(folder)
        try:
            with self._database.transaction() as session:
                account = FinancialAccount(
                    id=uuid7(),
                    slug=plan.slug,
                    display_name=normalized.display_name,
                    institution=plan.institution,
                    kind=plan.kind,
                    default_currency=plan.default_currency,
                    statement_adapter_key=plan.statement_adapter_key,
                    statement_account_identifier=normalized.statement_account_identifier,
                    statement_password_secret=normalized.statement_password_secret,
                    active=True,
                )
                session.add(account)
                session.flush()
                return self._record(account)
        except IntegrityError as error:
            folder.rmdir()
            raise FinancialAccountSetupError("Financial Account slug already exists") from error
        except Exception:
            folder.rmdir()
            raise

    def _validate(
        self,
        command: FinancialAccountBootstrapCommand,
    ) -> FinancialAccountBootstrapCommand:
        slug = command.slug.strip()
        if len(slug) > 80 or _SLUG_PATTERN.fullmatch(slug) is None:
            raise FinancialAccountSetupError("Financial Account slug must be lowercase kebab-case")
        display_name = self._normalize(command.display_name, "display name", maximum=160)
        institution = command.institution.strip().casefold()
        if _INSTITUTION_PATTERN.fullmatch(institution) is None or len(institution) > 80:
            raise FinancialAccountSetupError("institution must be lowercase kebab-case")
        currency = command.default_currency.strip().upper()
        if _CURRENCY_PATTERN.fullmatch(currency) is None:
            raise FinancialAccountSetupError("default currency must be an ISO 4217 code")
        if command.kind is not FinancialAccountKind.CREDIT_CARD:
            raise FinancialAccountSetupError(
                "only credit_card Financial Accounts are supported currently"
            )
        adapter_institution = self._adapters.get(command.statement_adapter_key)
        if adapter_institution is None:
            raise FinancialAccountSetupError(
                "statement adapter is not accepted for this deployment"
            )
        if adapter_institution != institution:
            raise FinancialAccountSetupError("statement adapter does not match institution")
        identifier = command.statement_account_identifier.strip()
        if not identifier or len(identifier) > 255:
            raise FinancialAccountSetupError("statement account identifier is required")
        secret = command.statement_password_secret
        if secret is not None:
            secret = secret.strip()
            if _SECRET_NAME_PATTERN.fullmatch(secret) is None:
                raise FinancialAccountSetupError("statement password secret reference is invalid")
        return FinancialAccountBootstrapCommand(
            slug=slug,
            display_name=display_name,
            institution=institution,
            kind=command.kind,
            default_currency=currency,
            statement_adapter_key=command.statement_adapter_key,
            statement_account_identifier=identifier,
            statement_password_secret=secret,
        )

    def _validate_password_secret(self, secret: str | None) -> None:
        if secret is None:
            return
        if self._password_root.is_symlink() or not self._password_root.is_dir():
            raise FinancialAccountSetupError("statement password root is not a directory")
        path = self._password_root / secret
        try:
            metadata = path.lstat()
        except FileNotFoundError as error:
            raise FinancialAccountSetupError("statement password secret was not found") from error
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise FinancialAccountSetupError("statement password secret must be a regular file")
        if metadata.st_mode & 0o077:
            raise FinancialAccountSetupError("statement password secret permissions are too broad")
        if not path.read_text(encoding="utf-8").rstrip("\r\n"):
            raise FinancialAccountSetupError("statement password secret is empty")

    def _validate_inbox_target(self, slug: str) -> None:
        if self._inbox_root.exists() and (
            self._inbox_root.is_symlink() or not self._inbox_root.is_dir()
        ):
            raise FinancialAccountSetupError("statement inbox root is not a directory")
        target = (self._inbox_root / slug).resolve()
        if target.parent != self._inbox_root:
            raise FinancialAccountSetupError("Financial Account inbox folder is unsafe")
        if target.exists():
            raise FinancialAccountSetupError("Financial Account inbox folder already exists")

    def _create_inbox_target(self, folder: Path) -> None:
        self._inbox_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._inbox_root.is_symlink() or not self._inbox_root.is_dir():
            raise FinancialAccountSetupError("statement inbox root is not a directory")
        folder.mkdir(mode=0o700)
        if folder.is_symlink() or not folder.is_dir():
            raise FinancialAccountSetupError("Financial Account inbox folder is unsafe")
        folder.chmod(0o700)

    @staticmethod
    def _configured_adapters() -> dict[str, str]:
        from billzebub.statement_adapters import configured_statement_adapters

        return {adapter.key: adapter.institution for adapter in configured_statement_adapters()}

    @staticmethod
    def _normalize(value: str, name: str, *, maximum: int) -> str:
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > maximum:
            raise FinancialAccountSetupError(f"{name} is required")
        return normalized

    @staticmethod
    def _record(account: FinancialAccount) -> FinancialAccountRecord:
        if account.statement_adapter_key is None:
            raise FinancialAccountSetupError("statement adapter is required")
        return FinancialAccountRecord(
            id=account.id,
            slug=account.slug,
            display_name=account.display_name,
            institution=account.institution,
            kind=account.kind,
            default_currency=account.default_currency,
            statement_adapter_key=account.statement_adapter_key,
            active=account.active,
        )
