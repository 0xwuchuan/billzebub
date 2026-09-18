# In-app Expense categorization

After statement confirmation or a Real-time Claim becoming a Transaction, an Expense or Cash Withdrawal starts `Uncategorized` with a `categorization_needed` Attention Review. The **NAS worker** then calls **Jev** (TypeSafe System One) and applies a Category when confidence is at least **0.5**. Below that floor the Review stays open. There is no learned Counterparty map, keyword scorer, or Codex runner.

## When Reviews appear and Jev runs

1. **Statement confirmation.** After Reconciliation establishes a Transaction (statement-only or matched Real-time Claim), Financial History records `Uncategorized` Category Splits for spending kinds and opens `categorization_needed`. The worker enqueues the same `categorize_transaction` job for every confirmation and calls Jev.
2. **Real-time Claim → Transaction.** When Reconciliation confirms a Wallet/PayLah Real-time Claim into a Transaction, that confirmation uses the same categorize hook. Owner-workspace projections of *provisional* Real-time Claims (not yet Transactions) do not call TypeSafe on read; they stay without Category Splits until confirmation. Daily NAS catch-up covers leftover uncategorized Transactions, including Wallet-originated ones Jev missed on the inline pass.

Transfers, Income, Refunds, and Reimbursements are never given Expense Categories.

## Owner categorization

Owner categorization uses `OwnerTransactionActions.categorize` with an ETag/version check and Correction reason `owner_categorization`. That cancels the Review. It does **not** upsert a Counterparty→Category map. A later Transaction with the same Counterparty stays Uncategorized until the owner or Jev assigns it again.

Agent categorization uses the same owner-safe mutation path with reason `agent_categorization` and also does not write a map. In-worker Jev uses reason `jev_categorization`.

## Auto-categorizer (NAS worker)

Unknowns stay as Reviews until Jev applies or the owner assigns. Cascade: statement import / Real-time Claim confirmation → worker Jev (threshold 0.5) → owner. A daily in-worker catch-up (`0 21 * * *` Asia/Singapore, env-overridable) drains remaining `categorization_needed` Reviews. This is not a Grok Bot and is not scheduled on forge. See [`docs/jev-categorizer.md`](jev-categorizer.md).

Every `categorize_transaction` pass that actually calls Jev (apply, skip, or TypeSafe error), including daily catch-up, appends a `jev_categorization_attempt` row. Pending Review `context.jev_attempt` is the latest row for that Transaction so the owner can see why categorization is still needed.
