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

# Typographic single quotes that iOS / smart punctuation emit instead of U+0027.
# Applied after NFKC (which already folds fullwidth U+FF07 to apostrophe).
_APOSTROPHE_FOLD = str.maketrans(
    {
        "\u00b4": "'",  # ACUTE ACCENT
        "\u02b9": "'",  # MODIFIER LETTER PRIME
        "\u02bc": "'",  # MODIFIER LETTER APOSTROPHE
        "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
        "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK
        "\u201a": "'",  # SINGLE LOW-9 QUOTATION MARK
        "\u201b": "'",  # SINGLE HIGH-REVERSED-9 QUOTATION MARK
        "\u2032": "'",  # PRIME
    }
)


class FinancialAccountAliasError(ValueError):
    """A local Financial Account alias is invalid or ambiguous."""


def normalize_apple_wallet_card_label(value: str) -> str:
    """Canonical form used to compare Shortcut labels with stored aliases.

    Folds, in order:

    1. Unicode NFKC compatibility composition
    2. Typographic / smart single quotes to ASCII apostrophe U+0027
    3. Trim and collapse Unicode whitespace, including newlines
    4. Casefold

    Distinct card names stay distinct. Blank labels are invalid.
    """
    compact = " ".join(
        unicodedata.normalize("NFKC", value).translate(_APOSTROPHE_FOLD).split()
    ).casefold()
    if not compact or len(compact) > 160:
        raise FinancialAccountAliasError("Apple Wallet card label is invalid")
    return compact


@dataclass(frozen=True, slots=True)
class AppleWalletAccountRecord:
    id: UUID
    default_currency: str


@dataclass(frozen=True, slots=True)
class FinancialAccountAliasRecord:
    id: UUID
    financial_account_id: UUID
    alias_kind: str
    display_label: str


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
        normalized = normalize_apple_wallet_card_label(card_label)
        with self._database.transaction() as session:
            rows = session.execute(
                select(
                    FinancialAccount.id,
                    FinancialAccount.default_currency,
                    FinancialAccountAlias.value,
                )
                .join(
                    FinancialAccountAlias,
                    FinancialAccountAlias.financial_account_id == FinancialAccount.id,
                )
                .where(
                    FinancialAccount.active.is_(True),
                    FinancialAccountAlias.alias_kind == self._APPLE_WALLET_CARD,
                )
            ).all()
        accounts = {
            row.id: row.default_currency
            for row in rows
            if _stored_alias_matches(row.value, normalized)
        }
        if len(accounts) != 1:
            return None
        account_id, currency = next(iter(accounts.items()))
        return AppleWalletAccountRecord(id=account_id, default_currency=currency)

    def _add_apple_wallet_card(
        self,
        card_label: str,
        *,
        account_slug: str | None = None,
        account_id: UUID | None = None,
    ) -> FinancialAccountAliasRecord:
        normalized = normalize_apple_wallet_card_label(card_label)
        with self._database.transaction() as session:
            account = self._active_account(
                session, account_slug=account_slug, account_id=account_id
            )
            existing = self._matching_alias(session, normalized)
            if existing is not None:
                if existing.financial_account_id == account.id:
                    self._heal_normalized_value(session, existing, normalized)
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
    def owner_card_label(cls, value: str) -> str:
        """Owner-safe Wallet card name or last4. Do not bullet-mask display labels."""
        return " ".join(value.split())

    @classmethod
    def _record(cls, alias: FinancialAccountAlias) -> FinancialAccountAliasRecord:
        return FinancialAccountAliasRecord(
            id=alias.id,
            financial_account_id=alias.financial_account_id,
            alias_kind=alias.alias_kind,
            display_label=cls.owner_card_label(alias.value),
        )

    def _matching_alias(self, session: Session, normalized: str) -> FinancialAccountAlias | None:
        aliases = session.scalars(
            select(FinancialAccountAlias).where(
                FinancialAccountAlias.alias_kind == self._APPLE_WALLET_CARD
            )
        ).all()
        matches = [alias for alias in aliases if _stored_alias_matches(alias.value, normalized)]
        if not matches:
            return None
        account_ids = {alias.financial_account_id for alias in matches}
        if len(account_ids) > 1:
            raise FinancialAccountAliasError("Apple Wallet card label is already mapped")
        return matches[0]

    def _heal_normalized_value(
        self,
        session: Session,
        alias: FinancialAccountAlias,
        normalized: str,
    ) -> None:
        if alias.normalized_value == normalized:
            return
        occupied = session.scalar(
            select(FinancialAccountAlias.id).where(
                FinancialAccountAlias.alias_kind == self._APPLE_WALLET_CARD,
                FinancialAccountAlias.normalized_value == normalized,
                FinancialAccountAlias.id != alias.id,
            )
        )
        if occupied is None:
            alias.normalized_value = normalized


def _stored_alias_matches(stored_value: str, normalized: str) -> bool:
    try:
        return normalize_apple_wallet_card_label(stored_value) == normalized
    except FinancialAccountAliasError:
        return False
