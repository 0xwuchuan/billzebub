"""Monopoly bridge that recovers exact strings before its float transformation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from billzebub.statement_extraction import (
    SourceLocator,
    StatementAdapterError,
    StatementCandidate,
    StatementRowCandidate,
)


@dataclass(frozen=True, slots=True)
class MonopolyStatementMetadata:
    statement_identity: str
    account_identifier: str
    statement_date: date
    period_start: date
    period_end: date
    currency: str
    opening_balance_text: str
    closing_balance_text: str


@dataclass(frozen=True, slots=True)
class MonopolyStatementSelection:
    """One Financial Account's metadata and in-scope source lines."""

    metadata: MonopolyStatementMetadata
    includes_line: Callable[[int, int], bool]


def _never_ignore(_line: str) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class MonopolyAdapterDefinition:
    bank: type[Any]
    candidate_line_pattern: re.Pattern[str]
    selection: Callable[[Any, str | None], MonopolyStatementSelection]
    kind_hint: Callable[[str, str | None], str | None]
    ignores_line: Callable[[str], bool] = _never_ignore
    account_identifiers: Callable[[Any], tuple[str, ...]] | None = None


class MonopolyStatementAdapter:
    """Expose Monopoly only as an exact, provenance-preserving statement adapter."""

    def __init__(
        self,
        *,
        key: str,
        adapter_version: str,
        institution: str,
        definition: MonopolyAdapterDefinition,
    ) -> None:
        self.key = key
        self.version = f"monopoly-{package_version('monopoly-core')}+{adapter_version}"
        self.institution = institution
        self._definition = definition

    def discover_account_identifiers(
        self,
        path: Path,
        passwords: tuple[SecretStr, ...],
    ) -> tuple[str, ...]:
        """Return statement account selectors without exposing statement rows."""
        # Monopoly imports remain confined to this adapter module.
        from monopoly.pdf import (  # type: ignore[import-untyped]
            MissingOCRError,
            MissingPasswordError,
            PdfDocument,
            PdfParser,
            WrongPasswordError,
        )
        from monopoly.pipeline import Pipeline  # type: ignore[import-untyped]

        configured_passwords = list(passwords) if passwords else [SecretStr("")]
        try:
            document = PdfDocument(path, passwords=configured_passwords)
            document.unlock_document()
            parser = PdfParser(self._definition.bank, document)
            statement = Pipeline(parser).handler.statement
            identifiers = (
                self._definition.account_identifiers(statement)
                if self._definition.account_identifiers is not None
                else (self._definition.selection(statement, None).metadata.account_identifier,)
            )
            normalized = tuple(dict.fromkeys(identifier.strip() for identifier in identifiers))
            if not normalized or any(not identifier for identifier in normalized):
                raise StatementAdapterError("account_identifier_missing")
            return normalized
        except MissingPasswordError as error:
            raise StatementAdapterError("password_required", {"password_required": True}) from error
        except WrongPasswordError as error:
            raise StatementAdapterError("wrong_password", {"password_required": True}) from error
        except MissingOCRError as error:
            raise StatementAdapterError("ocr_required", {"ocr_required": True}) from error
        except StatementAdapterError:
            raise
        except Exception as error:
            raise StatementAdapterError("monopoly_adapter_failed") from error

    def extract(
        self,
        path: Path,
        passwords: tuple[SecretStr, ...],
        expected_account_identifier: str | None = None,
    ) -> StatementCandidate:
        # Monopoly imports remain confined to this adapter module.
        from monopoly.pdf import (
            MissingOCRError,
            MissingPasswordError,
            PdfDocument,
            PdfParser,
            WrongPasswordError,
        )
        from monopoly.pipeline import Pipeline
        from monopoly.statements.base import MatchContext  # type: ignore[import-untyped]
        from monopoly.statements.transaction import RawTransaction  # type: ignore[import-untyped]

        configured_passwords = list(passwords) if passwords else [SecretStr("")]
        try:
            document = PdfDocument(path, passwords=configured_passwords)
            document.unlock_document()
            parser = PdfParser(self._definition.bank, document)
            statement = Pipeline(parser).handler.statement
            selection = self._definition.selection(statement, expected_account_identifier)
            metadata = selection.metadata
            rows: list[StatementRowCandidate] = []
            candidate_row_count = 0

            for page_index, page in enumerate(statement.pages, start=1):
                for line_index, line in enumerate(page.lines, start=1):
                    if not selection.includes_line(page_index, line_index):
                        continue
                    if self._definition.ignores_line(line):
                        continue
                    candidate_match = self._definition.candidate_line_pattern.search(line)
                    match = statement.pattern.search(line)
                    if candidate_match is None:
                        if match is not None and not statement._check_bound(match):
                            raise StatementAdapterError("unclassified_transaction_line")
                        continue
                    candidate_row_count += 1
                    if match is None or statement._check_bound(match):
                        continue
                    fields = match.groupdict()
                    raw_posting_date = fields.get("posting_date")
                    raw = RawTransaction(
                        match=match,
                        page_number=page_index - 1,
                        description=fields["description"],
                        amount=fields["amount"],
                        transaction_date=fields.get("transaction_date"),
                        polarity=fields.get("polarity"),
                        balance=fields.get("balance"),
                    )
                    raw = statement.pre_process_match(raw)
                    raw = statement.process_match(
                        raw,
                        MatchContext(
                            line=line,
                            lines=page.lines,
                            idx=line_index - 1,
                            description=raw.description,
                            multiline_config=statement.config.multiline_config,
                        ),
                    )
                    if raw.transaction_date is None:
                        raise StatementAdapterError("transaction_date_missing")
                    effective_polarity = raw.polarity
                    if effective_polarity is None and self._is_parenthesized_credit(raw.amount):
                        effective_polarity = "CR"
                    posted_amount = self._normalized_effect(raw.amount, effective_polarity)
                    provider_date = self._transaction_date(
                        raw.transaction_date,
                        metadata.statement_date,
                        statement.config.transaction_date_format,
                    )
                    posting_date = (
                        self._transaction_date(
                            raw_posting_date,
                            metadata.statement_date,
                            statement.config.transaction_date_format,
                        )
                        if raw_posting_date is not None
                        else provider_date
                    )
                    rows.append(
                        StatementRowCandidate(
                            raw_description=" ".join(raw.description.split()),
                            posted_amount_text=posted_amount,
                            provider_transaction_date=provider_date,
                            posting_date=posting_date,
                            transaction_kind_hint=self._definition.kind_hint(
                                raw.description,
                                effective_polarity,
                            ),
                            locator=SourceLocator(
                                page_number=page_index,
                                line_number=line_index,
                                text_start=match.start(),
                                text_end=match.end(),
                                text_sha256=hashlib.sha256(line.encode()).hexdigest(),
                            ),
                        )
                    )
        except MissingPasswordError as error:
            raise StatementAdapterError("password_required", {"password_required": True}) from error
        except WrongPasswordError as error:
            raise StatementAdapterError("wrong_password", {"password_required": True}) from error
        except MissingOCRError as error:
            raise StatementAdapterError("ocr_required", {"ocr_required": True}) from error
        except StatementAdapterError:
            raise
        except Exception as error:
            raise StatementAdapterError("monopoly_adapter_failed") from error

        return StatementCandidate(
            statement_identity=metadata.statement_identity,
            account_identifier=metadata.account_identifier,
            statement_date=metadata.statement_date,
            period_start=metadata.period_start,
            period_end=metadata.period_end,
            currency=metadata.currency,
            opening_balance_text=metadata.opening_balance_text,
            closing_balance_text=metadata.closing_balance_text,
            candidate_row_count=candidate_row_count,
            rows=tuple(rows),
        )

    @staticmethod
    def _is_parenthesized_credit(amount_text: str) -> bool:
        stripped = amount_text.strip()
        return stripped.startswith("(") and stripped.endswith(")")

    @staticmethod
    def _normalized_effect(amount_text: str, polarity: str | None) -> str:
        cleaned = re.sub(r"[^\d.\-]", "", amount_text)
        try:
            amount = Decimal(cleaned)
        except InvalidOperation as error:
            raise StatementAdapterError("invalid_decimal_string") from error
        if not amount.is_finite():
            raise StatementAdapterError("invalid_decimal_string")
        is_credit = polarity in {"CR", "+"} or MonopolyStatementAdapter._is_parenthesized_credit(
            amount_text
        )
        effect = abs(amount) if is_credit else -abs(amount)
        return format(effect, "f")

    @staticmethod
    def _transaction_date(
        raw_date: str,
        statement_date: date,
        configured_format: str,
    ) -> date:
        date_format = configured_format
        value = raw_date
        has_year = bool(re.search(r"\b\d{4}\b", raw_date)) or "y" in date_format.casefold()
        if not has_year:
            value = f"{raw_date} {statement_date.year}"
            date_format = f"{date_format} %Y"
        try:
            parsed = datetime.strptime(value, date_format).replace(tzinfo=UTC).date()
        except ValueError as error:
            raise StatementAdapterError("transaction_date_invalid") from error
        if not has_year and statement_date.month in {1, 2} and parsed.month > 2:
            parsed = parsed.replace(year=parsed.year - 1)
        return parsed
