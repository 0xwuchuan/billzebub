# Personal Finance Tracking

Billzebub builds a trustworthy personal financial history from activity reported by external financial providers.

## Language

**Source Artifact**:
An original statement, notification, export, or captured device event from which financial activity can be claimed.
_Avoid_: Input file, source document

**Extraction**:
A versioned attempt to derive a complete set of Claims from one Source Artifact. A statement Extraction is staged and accepted atomically only after source-specific validation; a failed Extraction creates no Claims.
_Avoid_: Import, parse result

**Claim**:
An immutable assertion about financial activity extracted from one Source Artifact through an accepted Extraction. A Claim may be provisional, duplicated, conflicting, incomplete, or incorrect and is not itself a trusted Transaction.
_Avoid_: Observation, transaction

**Real-time Claim**:
A Claim captured near the time financial activity occurs, such as one received from Apple Pay or a payment notification. It supplies the activity time and immediate details but remains provisional until confirmed.
_Avoid_: Pending transaction, live transaction

**Statement Claim**:
A Claim extracted from a periodic financial statement. It may confirm a matching Real-time Claim or establish a Transaction by itself, and retains the provider's posted details.
_Avoid_: Statement transaction, CSV row

**Transaction**:
A trusted financial movement established by a validated Statement Claim, optionally reconciled with a Real-time Claim. When both exist, its occurrence time comes from the Real-time Claim and its posted financial effect comes from the Statement Claim.
_Avoid_: Claim, expense, ledger entry

**Financial Account Effect**:
The signed economic direction of an amount on a Financial Account. Positive increases an asset or reduces a liability; negative decreases an asset or increases a liability. Claims preserve the provider's raw notation in source evidence but normalize Authorized and Posted Amounts to this convention.
_Avoid_: Debit, credit, absolute amount

**Authorized Amount**:
The Financial Account Effect reported near the time activity occurs, before the provider posts its final effect.
_Avoid_: Final amount, posted amount

**Posted Amount**:
The final Financial Account Effect applied to a Financial Account and reported by its Statement Claim. Confirmed spending uses this amount.
_Avoid_: Authorized amount, original amount

**Claim Disposition**:
The current conclusion about how a Claim participates in the financial history: Provisional, Confirmed, Unconfirmed, or Excluded. A Confirmed Claim supports a trusted Transaction, either because a validated Statement Claim established it directly or because Reconciliation linked multiple Claims; changing the disposition does not alter the Claim's captured content.
_Avoid_: Claim status, Reconciled

**Correction**:
A user-authored assertion about a Transaction's effective facts that preserves the Claims, prior Corrections, and complete amendment history.
_Avoid_: Edit, replacement

**Reconciliation**:
The determination of which Claims describe the same financial movement and whether their combined facts are trustworthy enough to establish a Transaction.
_Avoid_: Deduplication, import

**Financial Account**:
A provider-held balance or liability whose activity Billzebub tracks, such as a bank account, credit-card account, or PayLah wallet. Each tracked card is represented directly as its own Financial Account.
_Avoid_: Payment instrument, card token

**Counterparty**:
The canonical person or organization on the other side of financial activity. Claims retain their raw descriptions while aliases such as differently formatted merchant names may resolve to the same Counterparty.
_Avoid_: Description, merchant

**Transfer**:
A movement of value between Financial Accounts that does not itself represent income or an Expense, such as funding PayLah from a DBS account or paying a credit-card balance.
_Avoid_: Expense, top-up

**Transaction Kind**:
The effective classification of a Transaction as an Expense, Income, Transfer, Refund, Reimbursement, or Cash Withdrawal. Changing it requires a Correction and may change the effective ledger presentation without altering any Claim.
_Avoid_: Category, Claim Disposition

**Expense**:
A Transaction classified as spending rather than Income, a Transfer, a Refund, or another Transaction Kind.
_Avoid_: Transaction, purchase

**Income**:
Value received that is not a Transfer, Refund, or Reimbursement. V1 preserves Income from complete statement Extractions but does not categorize or emphasize it in the default expense workflow.
_Avoid_: Refund, reimbursement, incoming transaction

**Category**:
An editable reporting classification for Expenses, consisting of a top-level category and an optional subcategory.
_Avoid_: Account, tag

**Category Split**:
An allocation of one Expense across multiple Categories whose amounts together equal the Expense's Posted Amount.
_Avoid_: Tag, partial transaction

**Refund**:
Value returned against one or more earlier Expenses. It reduces net spending through Offset Allocations rather than counting as income.
_Avoid_: Income, reimbursement

**Reimbursement**:
Value received from another party to repay some or all of one or more earlier Expenses. It reduces net spending through Offset Allocations rather than counting as ordinary income.
_Avoid_: Refund, income

**Offset Allocation**:
An exact monetary allocation linking part or all of a Refund or Reimbursement to an earlier Expense. Multiple allocations may exist on either side but cannot exceed the value available from the offsetting Transaction or the linked Expense.
_Avoid_: Category Split, income

**Cash Withdrawal**:
An Expense representing cash removed from a Financial Account when cash itself is not tracked as a Financial Account.
_Avoid_: Transfer

**Reporting Currency**:
The currency in which Billzebub summarizes financial activity. SGD is the initial Reporting Currency; original and posted monetary values retain their own currencies.
_Avoid_: Transaction currency, settlement currency

**Pending Review**:
A durable request for a user or external agent decision associated with a Source Artifact, Extraction, Claim, or Transaction. It remains Pending until an explicit decision resolves it or its underlying condition disappears and cancels it; its severity is Attention or Blocking, where Blocking stops only the affected work. Examples include a failed statement Extraction, an unmatched Real-time Claim after sufficient subsequent statement history has been processed, or a Transaction whose classification is uncertain.
_Avoid_: Failed transaction, uncategorized expense, notification, dismissible alert
