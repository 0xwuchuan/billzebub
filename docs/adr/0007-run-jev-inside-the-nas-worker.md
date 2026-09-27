# Run Jev inside the NAS worker

The NAS worker is the production auto-categorizer: after statement confirmation (including a matched Real-time Claim) and after a new claim-only provisional Apple Wallet Real-time Claim, it calls TypeSafe Jev and applies a Category when Choice confidence is at least 0.5 and the Choice maps uniquely to an active catalog Category. A daily in-worker catch-up at 21:00 Asia/Singapore drains leftover `categorization_needed` Reviews and those still-uncategorized claim-only provisionals. Statement Reconciliation copies a Claim Category onto the resulting Transaction. Conversational agents, MCP, and owner-chosen models stay outside Billzebub as in ADR 0003; Jev is a system job with an agent-safe field set, not a chat runtime.

This supersedes the host-side / forge webhook path. The TypeSafe API key lives on rafiki as a mode-`0600` secret the worker already mounts. `scripts/agent/jev_categorize.py` remains an optional ops CLI and is not the production path; it uses the same `billzebub.jev` propose/apply path as the worker.

## Consequences

- The worker image includes `typesafe-sdk` and joins the Compose `egress` network solely so it can reach `https://api.typesafe.ai`.
- Missing key, low confidence, skip, or TypeSafe failure leaves the Transaction Uncategorized with `categorization_needed` (fail closed).
- Each Jev propose (apply or skip) appends `jev_categorization_attempt` so the owner can see why a Review remains. TypeSafe API keys are never stored or logged.
- No forge routine, Grok Bot, or webhook is required for production categorization.
