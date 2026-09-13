# Recommended build: Quiet Rail with Ledgerline and Ledger Desk grafts

`index.html` is Quiet Rail (candidate 1) with four grafts applied. Open the file directly in a browser. There is no build step, no server, and no network dependency beyond the Inter webfont, which falls back to the system sans stack when it cannot load.

## Grafts

**Overview keeps one continuous statement instead of four surfaces.** The three detached `.metric` cards and the `.attention-card` prompt are gone. A single `.statement` card now holds four cells divided by hairline borders, in the shape of Ledgerline's `.summary-ledger`. Cell one carries estimated spending and the seven-day bars. Cells two, three, and four carry Confirmed, Provisional, and Pending Review, each with a live count in its footer. Confirmed and Provisional route to the filtered Transactions list. Pending Review routes to the Review desk, and its dot and value turn red while a blocking failed Extraction is open.

**Review is a two-pane desk instead of a card list.** The left pane is the queue. The right pane is the evidence and the permitted actions for the selected item, following Ledgerline's `.review-layout`. Each queue row shows the condition, the subject, the amount in question, and the age. The evidence pane shows the Financial Account, the raw source, the linked Claims, and only the actions that condition permits. Blocking items lead the queue, then oldest first. The rail and its review count are unchanged, so the badge still drops as you resolve items.

**Onboarding gates every step.** `STEPS` now carries a `valid()` predicate and a `hint` per step, so Continue stays disabled until the step is satisfied and the hint says why. The gates are one Financial Account watched, one successful inbox read, one Category kept, and one completed first Extraction. The inbox read borrows Ledger Desk's probe: **Test read** spins, then lists each Source Artifact with the parser that claims it, including the August DBS statement whose totals do not validate. That file is the same Source Artifact behind the blocking Pending Review, so setup and Review agree. Step dots past the current gate are disabled, and the **Skip to workspace** escape is deleted because a first run cannot half-finish. Toggling a Financial Account resets the probe and the Extraction, so a late change reopens the gates it invalidates. Re-entering Setup from the rail starts at step 1 and offers **Return to Overview**, which first-run visitors do not get.

**Motion plays once per context.** `isFresh(key)` marks a context key on first render for the session. Overview animates its strip and grows its bars on the first visit and stays still on every later visit and on every in-route update, which covers search, filters, and a resolved decision. Onboarding keys on the step number, so each step enters once while the probe and the Extraction update quietly inside it. The Review evidence pane keys on the selected item, so it enters when the selection changes and not when the queue re-renders.

## Click through it

1. Open `index.html`. First run lands on Setup step 1 of 5.
2. Click **Continue**. On the accounts step, turn every Financial Account off. Continue disables and the hint asks for at least one. Turn them back on and click **Continue**.
3. On the inbox step, Continue is disabled. Click **Test read**, wait for the probe, then click **Continue**. The probe lists five Source Artifacts and flags the one whose totals do not validate.
4. Turn every Category off to disable Continue again, turn one back on, and click **Continue**.
5. Click **Run first Extraction**, wait for it to finish, and read the summary. Click **Enter Overview**.
6. Overview enters once. The statement strip reads S$ 2,191.30 estimated, S$ 2,170.30 Confirmed, S$ 21.00 Provisional, and 5 Pending Review.
7. Click the **Pending Review** cell. The desk opens with the blocking failed Extraction selected.
8. Click **Keep quarantined**. A toast confirms the decision, the queue drops to four, the rail badge drops to four, and the selection advances to the next open item.
9. Click a **Category needed** row, choose a Category in the select, and click **Assign Category**. The queue drops to three.
10. Click **Transactions** in the rail. The Transaction you just categorized shows its new Category. Click **Provisional** to narrow the list to the two Real-time Claims, then **All**, then any row to open the drawer with its linked Claims. Press Escape to close it.
11. Click **Overview** in the rail. The strip and the bars do not replay their entrance.
12. Click **Setup** in the rail. Setup replays from step 1, all gates satisfied, with **Return to Overview** available.

## Constraints held

Every color resolves to a Flexoki Dark hex from the brief or to a `color-mix()` of those hexes. Candidate 1's one invented hover tone, `#221f1e`, is now `color-mix(in srgb, #282726 60%, #1c1b1a)`. The domain words stay Transaction, Claim, Pending Review, and Financial Account.

Motion follows the Emil rules. Entrances use `cubic-bezier(0.16, 1, 0.3, 1)`, the file contains no `ease-in` and no `scale(0)`, every UI transition and entrance runs at 240ms or less, and only `transform`, `opacity`, and color properties animate. `prefers-reduced-motion: reduce` cancels animations and press scales, and it also shortens the simulated probe and Extraction waits. The one duration above 300ms is the 640ms rotation of the probe spinner, which is a looping progress indicator rather than a state transition, and reduced motion stops it.

## Verification

A Chrome DevTools Protocol driver walks the whole click-through above with the network emulated offline, then asserts the grafts, the figures quoted in step 6, the frequency gate, the reduced-motion behavior, and a 420px layout. All 74 checks pass with no console errors. The driver and its screenshots live outside this directory, at `/tmp/bz-graft-verify/drive.mjs`, and re-run with:

```bash
google-chrome --headless=new --remote-debugging-port=9333 --no-sandbox \
  --user-data-dir=/tmp/bz-graft-verify/chrome-profile \
  file:///tmp/arena-billzebub-ui/synthesis/recommended/index.html &
node /tmp/bz-graft-verify/drive.mjs file:///tmp/arena-billzebub-ui/synthesis/recommended/index.html
```
