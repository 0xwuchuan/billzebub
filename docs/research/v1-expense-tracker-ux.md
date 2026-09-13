# V1 expense-tracker UX references

## Useful patterns

### Make review a first-class inbox

Copilot places imported transactions in a **To Review** section and lets users edit before marking them reviewed. Its transaction list supports searching, filtering, bulk review, and quick category changes. [Copilot dashboard](https://help.copilot.money/en/articles/6045480-dashboard-tab-overview) · [Copilot transactions](https://help.copilot.money/en/articles/9554412-transactions-tab-overview) · [Copilot web](https://help.copilot.money/en/articles/11780342-copilot-money-for-web)

Monarch likewise gives Transactions an explicit Needs Review state, list filter, bulk editing, and mobile swipe review. It can mark all new or only uncategorized activity for review. [Monarch reviewing transactions](https://help.monarch.com/hc/en-us/articles/5528707082516-Reviewing-Transactions)

**Billzebub implication:** Pending Review should be a queryable workflow state shared by the UI, HTTP API, and MCP adapter—not a notification-only feature.

### Distinguish provisional and confirmed activity

Actual Budget distinguishes uncleared activity from activity matched to the bank, and shows separate cleared and uncleared totals during reconciliation. [Actual reconciliation](https://actualbudget.org/docs/accounts/reconciliation/)

Monarch warns that edits to pending activity can be lost when matching to the posted version fails. [Monarch transaction tips](https://help.monarch.com/hc/en-us/articles/28953573066260-Tips-Tricks-for-Using-Monarch)

**Billzebub implication:** show provisional Real-time Claims in estimated totals while keeping them visually distinct from confirmed Transactions. Corrections and category decisions belong to the durable Transaction once one exists; unmatched Claims retain their own review lifecycle.

### Let summary views drill into the underlying transactions

Copilot's Cash Flow view presents income, spending, and net income, with category-level and transaction-level drill-down. [Copilot Cash Flow](https://help.copilot.money/en/articles/9682232-cash-flow-tab-overview)

Monarch's Cash Flow and Reports support breakdown by category or merchant and interactive drill-down into transaction lists. [Monarch Cash Flow](https://help.monarch.com/hc/en-us/articles/20504904768020-Cash-Flow) · [Monarch Reports](https://help.monarch.com/hc/en-us/articles/21846787088916-Using-Reports)

**Billzebub implication:** the v1 dashboard needs only current-month totals and category breakdown, but every number should link to a filtered transaction list.

### Preserve raw source information separately from the cleaned display

Monarch rules distinguish the provider's original statement text from the cleaned merchant name. [Monarch transaction rules](https://help.monarch.com/hc/en-us/articles/360048393372-Transaction-Rules)

Actual Budget similarly separates imported payee text from a cleaned Payee and uses matching rules to resolve variants. [Actual payees](https://actualbudget.org/docs/transactions/payees/)

**Billzebub implication:** the normal transaction UI should show the canonical Counterparty, while transaction detail can explain the linked Claims and raw descriptions without treating them as editable display fields.

## Confirmed v1 surfaces

1. **Overview**
   - Current-month confirmed spending.
   - Eligible provisional spending.
   - Estimated total.
   - Top-level Category breakdown.
   - Counts for Pending Review and failed imports.
   - Every card links to a filtered Transactions or Review view.

2. **Transactions**
   - Search and filters for date, Financial Account, Category, Counterparty, confirmation state, and review state.
   - Provisional versus confirmed indicator.
   - Transaction detail showing effective values, linked Claims, Statement Claim posting details, Corrections, and audit history.
   - Category editing; Category Split UI may remain deferred even though the domain supports it.

3. **Review**
   - Separate queues for categorization ambiguity, unmatched Claims, reconciliation ambiguity, and failed imports.
   - Bulk review only where the same action is safe.
   - The same operations available through HTTP and MCP.

4. **Imports**
   - Source Artifact status, parser and version, validation result, statement period, account, and error details.
   - A failed statement remains quarantined and can be reprocessed after parser changes.

5. **Settings**
   - Financial Accounts and aliases.
   - Categories.
   - Ingestion folder and Financial Account configuration.
   - Configured/not-configured status for host-managed statement and mailbox secrets; secret values are changed through NAS setup commands, not the web UI.
   - Apple Shortcut and API/MCP token creation, scope, rotation, and revocation.

## V1 design language

Use Copilot Money as the primary reference for information hierarchy and interaction design: calm overview cards, prominent amounts, compact transaction rows, pill-like filters, progressive disclosure, and detail drawers rather than dense administration tables. This is a reference, not a pixel-for-pixel clone.

Use [Flexoki Dark](https://stephango.com/flexoki) as the fixed v1 color system:

- Page background: black `#100F0F`.
- Raised surfaces: base 950 `#1C1B1A`.
- Borders and quiet controls: base 900 `#282726`, with base 850 `#343331` for hover.
- Primary text: base 200 `#CECDC3`.
- Secondary text: base 500 `#878580`.
- Positive or confirmed: green 400 `#879A39`.
- Provisional: yellow 400 `#D0A215`.
- Destructive or failed: red 400 `#D14D41`.
- Primary interactive accent: cyan 400 `#3AA99F`.

Do not use color alone to communicate confirmation, review, or failure states; pair it with text and icons. Keep category colors subordinate to monetary amounts and workflow states.

Use Inter with tabular numerals for amounts. Follow Copilot's mixed-density approach: spacious summary cards on Overview and compact rows in Transactions, Review, and Imports. Use a left navigation rail on desktop, a compact top bar on narrow screens, and side drawers for detail so list context remains visible. Overview may use one restrained category ring paired with a ranked, exact-amount list; both drill into filtered Transactions.

V1 ships Flexoki Dark only. Light mode and user-defined themes are deferred.

## Explicitly defer

- Budgets and goals.
- Recurring and subscription views.
- Net worth and investment reporting.
- Custom dashboards and saved reports.
- Category rules and learned classifiers.
- Tags.
- Native mobile applications.
- Household collaboration.
- Rich chart libraries beyond a simple category breakdown and spending trend.
