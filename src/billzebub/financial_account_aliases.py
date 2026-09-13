"""Private local aliases that connect device labels to Financial Accounts."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
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


class FinancialAccountAliases:
    """Map private Apple Wallet card labels without exposing account identifiers."""

    _APPLE_WALLET_CARD = "apple_wallet_card"

    def __init__(self, database: Database) -> None:
        self._database = database

    def add_apple_wallet_card(self, *, account_slug: str, card_label: str) -> None:
        normalized = self._normalize(card_label)
        with self._database.transaction() as session:
            account = session.scalar(
                select(FinancialAccount).where(
                    FinancialAccount.slug == account_slug.strip(),
                    FinancialAccount.active.is_(True),
                )
            )
            if account is None:
                raise FinancialAccountAliasError("active Financial Account was not found")
            existing = session.scalar(
                select(FinancialAccountAlias).where(
                    FinancialAccountAlias.alias_kind == self._APPLE_WALLET_CARD,
                    FinancialAccountAlias.normalized_value == normalized,
                )
            )
            if existing is not None:
                if existing.financial_account_id == account.id:
                    return
                raise FinancialAccountAliasError("Apple Wallet card label is already mapped")
            session.add(
                FinancialAccountAlias(
                    id=uuid7(),
                    financial_account_id=account.id,
                    alias_kind=self._APPLE_WALLET_CARD,
                    value=" ".join(card_label.split()),
                    normalized_value=normalized,
                )
            )

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

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
        if not normalized or len(normalized) > 160:
            raise FinancialAccountAliasError("Apple Wallet card label is invalid")
        return normalized
