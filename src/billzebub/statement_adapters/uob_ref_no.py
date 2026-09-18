"""Strip trailing UOB statement ``Ref No.`` tokens from merchant descriptions.

This is not Monopoly's ``REFERENCE_ID`` field. UOB leaves
`` Ref No. : <token>`` on the merchant line; Billzebub treats that suffix as
statement noise rather than Counterparty.
"""

from __future__ import annotations

import re

UOB_STATEMENT_REF_NO_SUFFIX = re.compile(r"\s*Ref No\.\s*:\s*\S+\s*$", re.IGNORECASE)


def rewrite_uob_statement_ref_no(value: str) -> str | None:
    """Return the suffix-stripped value, or ``None`` if a rewrite would be empty.

    Unchanged values that do not end with the suffix are returned as-is.
    """
    current = value
    changed = False
    while UOB_STATEMENT_REF_NO_SUFFIX.search(current):
        stripped = UOB_STATEMENT_REF_NO_SUFFIX.sub("", current, count=1).strip()
        if not stripped:
            return None
        current = stripped
        changed = True
    if not changed:
        return value
    return current


def strip_uob_statement_ref_no(value: str) -> str:
    """Remove trailing UOB ``Ref No.`` suffixes without emitting an empty string."""
    rewritten = rewrite_uob_statement_ref_no(value)
    return value if rewritten is None else rewritten
