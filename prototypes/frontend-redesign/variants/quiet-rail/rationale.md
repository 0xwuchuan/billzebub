# Quiet Rail

This prototype argues for one daily shape. A persistent left rail holds Overview, Review, and Transactions. The main pane changes density by job. The rail does not.

## Direction

Quiet Rail. Desktop chrome is a 15.5rem left rail with a small mark, daily destinations, and Setup in a footer group. Narrow screens swap that rail for a compact top strip. Detail opens in a right drawer so the list stays put.

The loudest type on Overview is the estimated September spend, not the product name. That is the opposite of the current `web/` hero.

## Axis

The axis is layout plus density, not a new color story.

The rail is the orientation device. Review is always one click away and carries a count. Overview stays the home. Transactions stay the archive. Density is a token, not a new layout per page. Overview uses a 36px amount, airy metric cards, a restrained category ring, and a compact recent strip. Review uses medium cards with decisions on the card. Transactions use 44px rows, date groups, and amount primacy with tabular numerals.

## Alternatives rejected

**Review First.** Landing on the inbox makes Pending Review the product. That is honest on a messy Monday and empty on a clean Tuesday. The badge already does the duty work. The home page should still explain the month when the queue is zero.

**Soft Ledger, the editorial column.** A magazine type scale and a stacked single column is what `web/` already does. A 4.5rem Billzebub wordmark forces Review and Transactions below the fold and trains the eye on branding instead of Posted Amount. A daily finance tool needs scan, not a cover page.

Quiet Rail keeps Copilot's mixed density and left-rail habit without cloning Copilot's marketing chrome.

## Motion

Tokens live on `:root`.

- `--bz-ease-out` is `cubic-bezier(0.16, 1, 0.3, 1)`. No ease-in on UI.
- Press on buttons, rail items, chips, and metric cards is `scale(0.97)` in 90ms.
- Stage enter is 8px translateY plus opacity in 220ms.
- The drawer moves 12px and fades in 240ms. Nothing uses `scale(0)`.
- Only `transform` and `opacity` animate.
- `prefers-reduced-motion` removes animation, transition, and press scale.

Frequency stays low. Rows do not bounce. The week strip is static height, not a looping chart.

## Density and copy

September 2026 is the fixture date. Amounts are SGD. Counterparties are Toast Box, FairPrice, Cold Storage, Grab, Uniqlo, SP Services, IncomeShield, and other local names. Domain words stay exact. Transaction, Claim, Real-time Claim, Statement Claim, Pending Review, Financial Account, Category, Extraction, Source Artifact, Correction.

Onboarding is five app steps. Workspace, Financial Accounts, Source Artifact inboxes, Categories, then a ready state. It records what the SPA should watch. It does not ask for compose files, SSH, or mailbox passwords.

## Extraction

`--bz-*` custom properties cover color, radius, space, type, control height, and motion. Primitive classes are `btn`, `field`, `select`, `chip`, `badge`, `card`, `row`, `rail-item`, and `drawer`. A later design system can lift those tokens and primitives without restyling each screen from scratch.

The prototype is throwaway HTML. It is an instrument for the visual decision, not a start on `web/`.
