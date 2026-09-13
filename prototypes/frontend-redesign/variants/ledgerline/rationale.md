# Ledgerline

## Direction

Ledgerline treats Billzebub as a daily financial desk. A centered horizontal shell keeps Overview, Review, and Transactions at the same level. The current date and reporting month anchor each visit. Review is a place to work, not a badge that sends the user elsewhere.

This prototype tests whether a time-first workspace feels calmer and more useful than a permanent navigation rail. It is a throwaway design instrument, not production code.

## Axis of divergence

The primary axis is temporal layout and density.

The shell is a wide daybook with top navigation. Overview opens with one continuous monthly ledger strip instead of a grid of detached cards. Confirmed Transactions, eligible Real-time Claims, and Pending Review share one reading line. Below that line, the screen moves from a spacious spending curve into exact category rows and today's queue.

Density increases with certainty and task focus:

- Overview leaves room around the few numbers that answer "How is September going?"
- Review pairs a compact queue with one large decision panel. Evidence stays visible before the user acts.
- Transactions uses grouped, scan-friendly rows and opens detail in a side drawer. The ledger remains in context.
- Onboarding uses a focused in-app layer with four short steps. It establishes a Financial Account, adds an activity source, validates the first Source Artifact, and hands unresolved work to Review.

## Information architecture

The daily loop is Overview, Review, then Transactions.

Overview answers what changed and what needs attention. Every amount drills into a filtered ledger. Review owns all uncertainty, including categorisation, Reconciliation, and failed Extraction. Transactions remains the trusted history and distinguishes provisional Claims from confirmed Transactions with both text and icons.

The layout deliberately avoids product areas that V1 does not need. There are no budgets, goals, net worth modules, or decorative insight cards.

## Alternatives rejected

- A conventional left rail was rejected because it makes a small daily tool read like an administration suite. It also spends permanent width on navigation that has only three primary destinations.
- A dashboard made from many equal cards was rejected because it recreates the current stacked-panel problem. Equal boxes make unlike information compete at the same volume.
- Review as a notification drawer was rejected because Pending Review is durable workflow state. It needs filters, evidence, and a stable work area.
- A bank-connection wizard was rejected because Billzebub is not a hosted aggregator. The setup flow teaches the Claim and Transaction distinction inside the product without exposing NAS commands.
- One dense ledger for every screen was rejected because summary reading and transaction scanning need different rhythms.

## Motion and controls

Entrances use opacity with a 6 to 18 pixel translation. View changes take 220 milliseconds, decision changes take 190 milliseconds, drawers take 240 milliseconds, and onboarding takes 260 milliseconds. Every curve is ease-out. Buttons press to `scale(0.97)`. No element enters from `scale(0)`.

Hover feedback stays under 180 milliseconds. Motion never carries information by itself. `prefers-reduced-motion` reduces transitions and removes the press transform.

Controls use quiet one-pixel borders, compact radii, clear focus rings, and restrained filled states. Status colors always appear with a label or icon.

## Flexoki and extraction

The prototype uses the fixed Flexoki Dark values for the page, surfaces, borders, text, and workflow accents. Inter and tabular numerals keep SGD amounts aligned.

The file starts with a token block and uses shared control classes for buttons, fields, badges, surfaces, rows, and motion. JavaScript keeps one explicit state shape for the active view, onboarding step, Review selection, transaction drawer, and ledger filters. A production pass can lift those pieces into design-system tokens, primitives, and state machines without copying screen-specific styles.

## Recommendation

Carry the horizontal daybook shell, the continuous monthly ledger strip, and the two-pane Review desk into a production design pass. Keep the transaction drawer and the four-step onboarding flow. Test the top navigation at narrow tablet widths before committing, because three labeled destinations fit now but future product areas could exceed the pattern.
