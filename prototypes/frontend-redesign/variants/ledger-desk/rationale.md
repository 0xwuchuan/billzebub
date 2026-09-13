# Candidate 3 — "Ledger Desk"

A calm Flexoki Dark SPA whose chrome almost disappears: navigation lives in a
command palette and a 56px glyph spine, and the space that a sidebar and card
grid would have taken is given back to editorial ledger typography.

Open `index.html` directly, or serve the folder and use the deep links:
`#/overview`, `#/transactions`, `#/review/unmatched`, `#/imports`,
`#/tokens`, `#/setup/2`, `#/tx/tx_grab_13`, `#/commands`.

## Direction name

**Ledger Desk** — a keyboard-first desk surface for money, not a dashboard.

## Axis of divergence

**Chrome-minimal command shell + editorial ledger density**, against the
obvious reading of the brief (labelled left rail, card-grid overview, dense
admin tables).

The two halves are one idea rather than two. If navigation is a command
palette (`⌘K`), `g o` / `g t` / `g r` chords and a glyph spine, then no
horizontal space is spent on labels, no vertical space on a page header, and
the canvas is free to be a measured 64rem column that reads like a statement:
a dateline, a sentence, one large number, then ruled rows. The hierarchy is
carried by type, rules and whitespace instead of by nested card borders. This
is the axis other candidates are least likely to take, because a review-first
inbox home or a Copilot-style card overview are both closer to the brief's
prior art table.

What it buys the daily user:

- **The daily loop is a keyboard loop.** Reviewing eleven transactions and
  categorizing four of them is a repeat task. `j` / `k` move, `↵` opens the
  detail drawer, `1`–`3` pick a permitted decision, `x` defers, `f` focuses
  search. The bottom "ledge" shows the three keys that matter on the current
  screen, so the shortcuts are discoverable rather than folklore.
- **Cards cost density.** Ruled rows fit 24 transactions with the canonical
  Counterparty, the raw provider text, the account, the Category, the
  confirmation state and a tabular amount without feeling packed.
- **Deep links.** Every screen, queue, drawer and setup step is addressable,
  which is what a future "3 Pending Review" notification needs to link into.

## Information architecture

Five destinations, each a different question, ordered by how often you ask it:

| Screen | The question it answers |
| --- | --- |
| Overview | Where does the month stand, and what is uncertain? |
| Transactions | What exactly happened, and what does this Counterparty do? |
| Review | What decision is Billzebub waiting on? |
| Imports | Did my statements land, and what got quarantined? |
| Design tokens | What exactly would we extract into a design system? |

Overview is a **statement, not a summary grid**. Confirmed spending,
provisional Real-time Claims and allocated Refunds are three ruled lines under
one estimated total, so the provisional/confirmed distinction is structural
rather than a badge colour. Every figure, category row, trend bar and decision
row drills into a filtered ledger or a review queue, and the numbers are
derived from the same fixture the ledger renders — resolve a case in the
review inbox and the Uncategorized bucket on Overview drops.

Review is a **queued inbox with four queues** (categorization and Kind,
unmatched Claims, reconciliation, failed Extractions) rather than a single
undifferentiated list, because the four need different evidence and offer
different permitted decisions. Each case shows its subject, why it is
uncertain, the Claims behind it, and only the decisions the domain allows.
Blocking severity is the only place red appears.

## What I rejected, and why

**Review-first inbox as the home screen.** Tempting, and the brief hints at
it, but it makes the daily answer to "how am I doing?" require a second
navigation, and it punishes the good case — an empty inbox — with an empty
home. The review count is instead persistent in the top bar and spine (with a
dot), and Overview's "Needs a decision" block is a direct queue-level
drill-in. I expect another candidate to take this axis, which is another
reason to leave it.

**A 240px labelled sidebar.** Five destinations do not need a labelled rail
occupying a quarter of a laptop's width. The spine shows tooltips with their
`g` chord on hover and focus, which teaches the keyboard shell rather than
replacing it.

**A category donut/ring.** The repo's UX doc allows "one restrained ring", but
a ring makes you compare arcs and then read the legend anyway. A ranked list
with exact amounts and a hairline bar is faster and keeps colour subordinate
to the amount — the bars use one dimmed cyan at varying width, never a
categorical palette.

**A modal "add transaction" flow and a chart library.** Out of the brief's
scope (`Correction`-based editing, not manual entry) and every visual here is
hand-rolled SVG-free CSS, so there is nothing to strip at extraction time.

**A NAS-style setup wizard in a card.** See below.

## Onboarding: frontend-native, five steps

`#/setup/0` or the "Finish setup" button. A full-surface flow with a step
spine on the left, a sticky footer, and a 2px progress meter — deliberately
*not* a modal wizard card, because first run is a full-attention task and a
dialog-in-a-dialog reads like a NAS appliance.

1. **Reporting basis** — Reporting Currency (SGD) and timezone, framed as
   "what should Billzebub summarize in", since original currencies stay on the
   Claims.
2. **Financial Accounts** — DBS Multiplier ···4821, DBS Live Fresh ···7702,
   PayLah! ···9014, each tracked card its own account.
3. **Statement ingestion** — a path field with a real "Test read" probe that
   reports the four Source Artifacts it found and the parser matched to each.
   Continue stays disabled until the folder is readable.
4. **Capture on iPhone** — creates a `claims:write` scoped token with a copy
   affordance and the three Shortcut steps. Skippable, and says so.
5. **First Extraction** — runs staged validation, then reports the honest
   outcome: 54 Claims accepted, 24 Transactions, 8 Pending Review, and one
   statement rejected and quarantined. It hands off to the review inbox.

Each step's Continue is gated on the thing that step establishes, so the flow
can't produce a half-configured workspace, and the step spine lets you jump
back without losing state.

## Motion

Tokens: `--bz-ease-out: cubic-bezier(.16,1,.3,1)` for entrances,
`--bz-ease-out-soft` for exits, durations `90 / 120 / 180 / 240ms` — 240ms is a
hard ceiling. Only `transform` and `opacity` animate; colour transitions are
the only exception and they are 120ms.

- **Press** is `scale(0.97)` at 90ms on every button, pill, choice and row
  affordance. Nothing ever scales from 0.
- **Route entrance** is `translateY(6px)` plus opacity at 180ms, staggered
  24ms across at most three blocks.
- **Frequency gate.** Motion is spent on rare events, not daily ones.
  In-route updates — filtering the ledger, typing in search, resolving a case
  — re-render with entrance motion suppressed (`.canvas.is-quiet`), and the
  trend bars and category meters ease out **once per route per session**.
  Glance at Overview a second time and the chart is simply there. The hero
  figure never count-ups: a number you read every morning should not perform.
- **Resolving a case** fades and lifts the card 4px over 180ms, then the list
  reflows without animation and a toast confirms the Correction. The exit is
  the only thing that moves, so your eye stays where the decision was.
- **Drawer** slides 18px with opacity at 240ms and is revealed with a forced
  style flush rather than a queued frame, so the transition cannot be dropped.
- **Reduced motion** collapses every duration and delay to 1ms, sets
  `--bz-press: 1` and `--bz-lift: 0`, drops overlay transforms, and stops the
  loading spinner outright rather than letting the blanket override spin it at
  1ms per revolution. The prototype was screenshot-verified under
  `--force-prefers-reduced-motion`.

## Density

Mixed, per screen intent:

- **Overview**: spacious. 32px serif headings, a 44px figure, 12px ruled
  splits, generous `--bz-s7` section gaps.
- **Transactions / Imports**: compact. 48px rows, 15px primary text, 11px
  monospace raw provider text as a second line, day marks with a day subtotal.
  Amounts are right-aligned tabular Inter so decimal points line up down the
  column.
- **Review**: spacious per case, because a case is a decision and should not
  be scanned. Evidence on the left, permitted decisions on a bordered right
  column with number keys.

Serif (`Iowan Old Style` → Georgia → `ui-serif`) for editorial headings gives
the app a documentary voice without touching the fixed Flexoki palette; Inter
with `tabular-nums` carries every number. Colour stays inside the four
sanctioned accents, and no state is communicated by colour alone — every badge
pairs a dot with a word (`Confirmed`, `Provisional`, `Review`, `Failed`).

## Extraction path

The CSS is written as the design system it wants to become: section 1 is the
only place a literal colour, duration or easing appears, and sections 3–6 are
component blocks (`.btn`, `.pill`, `.badge`, `.field`, `.input`, `.card`,
`.row`, `.case`, `.drawer`, `.palette`, `.step`) that map one-to-one onto
`<Button variant>`, `<Pill>`, `<Badge tone>`, `<Field>`, `<LedgerRow>`,
`<ReviewCase>`, `<Drawer>`, `<CommandPalette>` and `<SetupStep>`.

The `#/tokens` route is part of the prototype on purpose: it renders the ten
colour tokens, four durations, two easings, the type scale and every control
state from the same variables the app uses, so the extraction conversation
starts from a page you can point at.

## Honest gaps

Fixtures are in-memory, so decisions reset on reload. Category Split, offset
allocation pickers and the "match to an existing Transaction" flow open as
choices but not as their own sub-surfaces. Settings is represented only by the
tokens route. Touch gets a collapsed spine and a glyph command trigger, but
swipe-to-review is not prototyped.
