"""Exact monetary values at Billzebub's external seams."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Self

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    """An exact decimal amount paired with an ISO-style currency code."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money amount must be a Decimal")
        if not self.amount.is_finite():
            raise ValueError("Money amount must be finite")

        normalized_currency = self.currency.upper()
        if _CURRENCY_PATTERN.fullmatch(normalized_currency) is None:
            raise ValueError("Money currency must be a three-letter code")
        object.__setattr__(self, "currency", normalized_currency)

    @classmethod
    def parse(cls, amount: str | int | Decimal, currency: str) -> Self:
        """Parse trusted text or integer input while refusing floating point."""
        if isinstance(amount, float):
            raise TypeError("floating-point monetary values are forbidden")
        if isinstance(amount, bool):
            raise TypeError("boolean monetary values are forbidden")

        try:
            decimal_amount = amount if isinstance(amount, Decimal) else Decimal(amount)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Money amount must be a decimal string or integer") from error
        return cls(decimal_amount, currency)

    def to_wire(self) -> dict[str, str]:
        """Return the lossless JSON representation used by HTTP resources."""
        return {"amount": format(self.amount, "f"), "currency": self.currency}
