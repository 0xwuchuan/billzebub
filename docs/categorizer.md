# In-app Expense categorization

Billzebub does **not** auto-assign a Category in the NAS app. After statement confirmation or Real-time Claim projection, an Expense or Cash Withdrawal stays `Uncategorized` and keeps a `categorization_needed` Attention Review until the **owner** or **Jev** assigns a Category. There is no LLM, learned map, or keyword scorer in the NAS containers.

## When Reviews appear

1. **Statement confirmation.** After Reconciliation establishes a Transaction (statement-only or matched Real-time Claim), Financial History records `Uncategorized` Category Splits for spending kinds and opens `categorization_needed`.
2. **Real-time Claim → Transaction projection.** Owner workspace projections of eligible provisional Real-time Claims do not guess a Category. Display splits stay empty until a Statement Claim confirms a Transaction and a later owner or Jev assignment.

Transfers, Income, Refunds, and Reimbursements are never given Expense Categories.

## Owner categorization

Owner categorization uses `OwnerTransactionActions.categorize` with an ETag/version check and Correction reason `owner_categorization`. That cancels the Review. It does **not** upsert a Counterparty→Category map. A later Transaction with the same Counterparty stays Uncategorized until the owner or Jev assigns it again.

Agent categorization uses the same owner-safe mutation path with reason `agent_categorization` and also does not write a map.

## External auto-categorizer (host-side only)

Unknowns stay as Reviews. The only auto pass is host-side **Jev**: `scripts/agent/jev_categorize.py` calls TypeSafe System One (`jev-1.13.0`) against the agent API. It is not a Grok Bot and must not be added to `compose.nas.yaml` or the `api`/`worker` images. See [`docs/jev-categorizer.md`](jev-categorizer.md).
