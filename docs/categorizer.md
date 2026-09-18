# In-app Expense categorization

Billzebub auto-assigns a Category only when a deterministic pass reports **high confidence**. Anything weaker stays `Uncategorized` and keeps the existing `categorization_needed` Attention Review. There is no LLM in the NAS containers.

## When the pass runs

1. **Statement confirmation.** After Reconciliation establishes a Transaction (statement-only or matched Real-time Claim), the worker enqueues a `categorize_transaction` job for that Transaction. Review-driven Reconciliation decisions enqueue the same job.
2. **Real-time Claim → Transaction projection.** Owner workspace projections of eligible provisional Real-time Claims run the same scorer inline. High-confidence results appear as Category Splits on the projected row. They are display-only until a Statement Claim confirms a Transaction; assignment then uses the audited owner-categorize path.

Transfers, Income, Refunds, and Reimbursements are never given Expense Categories.

## Confidence

The scorer returns one Category or abstains. It never picks a winner among competing Categories.

| Source | Confidence | Default NAS behaviour |
|---|---|---|
| Owner-taught Counterparty map (exact normalized key) | `1.000` | Assigned |
| Counterparty tokens include an existing Category name (`Groceries`, `Dining`, …) | `1.000` | Assigned |
| Unique keyword synonym (`grocer` → Groceries, `cafe` → Dining, …) | `0.950` | Abstain unless the threshold is lowered |
| Ambiguous or unknown | `0.000` | Attention Review; no Category |

`BILLZEBUB_CATEGORIZER_MIN_CONFIDENCE` defaults to `1.000` (NAS-safe: only exact learned mappings and Category-name tokens). Lower it to `0.950` to enable unique keyword rules. `BILLZEBUB_CATEGORIZER_ENABLED=false` disables assignment entirely.

The pass only proposes Categories that already exist and are active. It will not create Dining, Gifts, Groceries, Health, Shopping, Transport, Utilities, or Uncategorized.

Low-confidence Transactions keep `categorization_needed`. High-confidence assignment uses `OwnerTransactionActions.categorize` with a system actor, ETag/version check, and Correction reason `auto_categorization`, which cancels that Review.

## How owner corrections teach the map

Owner (not agent, not auto) categorization upserts `counterparty_category_map`:

- **Key:** NFKD ASCII, casefolded, whitespace-collapsed Counterparty text.
- **Value:** the Category the owner just assigned.
- **Source:** `owner_categorization`.

Later passes look up that key first. A later owner correction overwrites the mapping. Auto-assignment does not write the map, so the system cannot train on its own guesses.

## External runners (host-side only)

Unknowns stay as Reviews. External passes run on forge against the agent API; they are not Grok Bots and must not be added to `compose.nas.yaml` or the `api`/`worker` images.

Cascade: **in-app map + rules → Jev → optional Codex**.

1. **Jev (primary).** `scripts/agent/jev_categorize.py` calls TypeSafe System One (`jev-1.13.0`). Fail-closed: catalog match, calibrated Choice confidence, and an evidence Noul. See [`docs/jev-categorizer.md`](jev-categorizer.md).
2. **Codex (optional fallback).** `scripts/agent/codex_categorize.py` still exists and is unchanged as a fallback (`codex exec -m gpt-5.6-luna`, terra fallback). See [`docs/codex-categorizer.md`](codex-categorizer.md).
