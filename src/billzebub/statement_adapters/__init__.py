"""Institution-specific adapters behind the Statement Extraction seam."""

from billzebub.statement_adapters.citi import citi_credit_card_adapter
from billzebub.statement_adapters.dbs import dbs_credit_card_adapter
from billzebub.statement_adapters.monopoly import (
    MonopolyAdapterDefinition,
    MonopolyStatementAdapter,
    MonopolyStatementMetadata,
    MonopolyStatementSelection,
)
from billzebub.statement_adapters.uob import uob_credit_card_adapter


def configured_statement_adapters() -> list[MonopolyStatementAdapter]:
    """Return only the institution adapters accepted for this deployment build."""
    return [
        dbs_credit_card_adapter(),
        citi_credit_card_adapter(),
        uob_credit_card_adapter(),
    ]


__all__ = [
    "MonopolyAdapterDefinition",
    "MonopolyStatementAdapter",
    "MonopolyStatementMetadata",
    "MonopolyStatementSelection",
    "citi_credit_card_adapter",
    "configured_statement_adapters",
    "dbs_credit_card_adapter",
    "uob_credit_card_adapter",
]
