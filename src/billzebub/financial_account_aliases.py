"""Private local aliases that connect device labels to Financial Accounts."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.persistence.models import FinancialAccount, FinancialAccountAlias

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class FinancialAccountAliasError(ValueError):
    """A local Financial Account alias is invalid or ambiguous."""


@dataclass(frozen=True, slots=True)
class AppleWalletAccountRecord:
    id: UUID
    default_currency: str


@dataclass(frozen=True, slots=True)
class FinancialAccountAliasRecord:
    id: UUID
    financial_account_id: UUID
    alias_kind: str
    masked_value: str


class FinancialAccountAliases:
    """Map private Apple Wallet card labels without exposing account identifiers."""

    _APPLE_WALLET_CARD = "apple_wallet_card"

    def __init__(self, database: Database) -> None:
        self._database = database

    def list(self) -> tuple[FinancialAccountAliasRecord, ...]:
        with self._database.transaction() as session:
            aliases = session.scalars(
                select(FinancialAccountAlias).order_by(
                    FinancialAccountAlias.created_at, FinancialAccountAlias.id
                )
            ).all()
            return tuple(self._record(alias) for alias in aliases)

    def add_apple_wallet_card(
        self,
        *,
        account_slug: str,
        card_label: str,
    ) -> FinancialAccountAliasRecord:
        return self._add_apple_wallet_card(card_label, account_slug=account_slug)

    def add_apple_wallet_card_for_account(
        self,
        account_id: UUID,
        *,
        card_label: str,
    ) -> FinancialAccountAliasRecord:
        return self._add_apple_wallet_card(card_label, account_id=account_id)

    def resolve_apple_wallet_card(self, card_label: str) -> AppleWalletAccountRecord | None:
        normalized = self._normalize(card_label)
        with self._database.transaction() as session:
            row = session.execute(
                select(FinancialAccount.id, FinancialAccount.default_currency)
                .join(
                    FinancialAccountAlias,
                    FinancialAccountAlias.financial_account_id == FinancialAccount.id,
                )
                .where(
                    FinancialAccount.active.is_(True),
                    FinancialAccountAlias.alias_kind == self._APPLE_WALLET_CARD,
                    FinancialAccountAlias.normalized_value == normalized,
                )
            ).one_or_none()
        if row is None:
            return None
        return AppleWalletAccountRecord(id=row.id, default_currency=row.default_currency)

    def _add_apple_wallet_card(
        self,
        card_label: str,
        *,
        account_slug: str | None = None,
        account_id: UUID | None = None,
    ) -> FinancialAccountAliasRecord:
        normalized = self._normalize(card_label)
        with self._database.transaction() as session:
            account = self._active_account(
                session, account_slug=account_slug, account_id=account_id
            )
            existing = session.scalar(
                select(FinancialAccountAlias).where(
                    FinancialAccountAlias.alias_kind == self._APPLE_WALLET_CARD,
                    FinancialAccountAlias.normalized_value == normalized,
                )
            )
            if existing is not None:
                if existing.financial_account_id == account.id:
                    return self._record(existing)
                raise FinancialAccountAliasError("Apple Wallet card label is already mapped")
            alias = FinancialAccountAlias(
                id=uuid7(),
                financial_account_id=account.id,
                alias_kind=self._APPLE_WALLET_CARD,
                value=" ".join(card_label.split()),
                normalized_value=normalized,
            )
            session.add(alias)
            session.flush()
            return self._record(alias)

    @staticmethod
    def _active_account(
        session: Session,
        *,
        account_slug: str | None,
        account_id: UUID | None,
    ) -> FinancialAccount:
        query = select(FinancialAccount).where(FinancialAccount.active.is_(True))
        if account_id is not None:
            query = query.where(FinancialAccount.id == account_id)
        elif account_slug is not None:
            query = query.where(FinancialAccount.slug == account_slug.strip())
        else:
            raise FinancialAccountAliasError("active Financial Account was not found")
        account = session.scalar(query)
        if account is None:
            raise FinancialAccountAliasError("active Financial Account was not found")
        return account

    @classmethod
    def mask_card_label(cls, value: str) -> str:
        compact = " ".join(value.split())
        if len(compact) <= 4:
            return "•" * max(len(compact), 1)
        return f"{compact[:2]}{'•' * (len(compact) - 4)}{compact[-2:]}"

    @classmethod
    def _record(cls, alias: FinancialAccountAlias) -> FinancialAccountAliasRecord:
        return FinancialAccountAliasRecord(
            id=alias.id,
            financial_account_id=alias.financial_account_id,
            alias_kind=alias.alias_kind,
            masked_value=cls.mask_card_label(alias.value),
        )

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
        if not normalized or len(normalized) > 160:
            raise FinancialAccountAliasError("Apple Wallet card label is invalid")
        return normalized
