# Frontend redesign prototype (throwaway)

Interactive Flexoki Dark design arena for Billzebub. Not production. Does not replace `web/`.

## Decision

Which calm product UI direction should later design-system and Feature work follow for shell, overview, app-native onboarding, transactions, and review?

**Recommendation: Quiet Rail chrome, with grafts** (see Project store `docs/frontend-design-directions.md`).

## Run

```bash
cd prototypes/frontend-redesign
python3 -m http.server 5174
```

Open http://127.0.0.1:5174

| Key | Variant |
| --- | --- |
| `1` | Recommended (Quiet Rail + grafts) |
| `2` | Quiet Rail (arena C1) |
| `3` | Ledgerline (arena C2) |
| `4` | Ledger Desk (arena C3) |

`←` / `→` also flip. `?v=2` deep-links. Click the bottom pill if a focused iframe ate the key event.

## Provenance

Arena candidates lived under `/tmp/arena-billzebub-ui/candidate-{1,2,3}/`. Synthesis notes under `/tmp/arena-billzebub-ui/synthesis/`.
