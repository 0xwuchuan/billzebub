# Run Jev inside the NAS worker

The NAS worker is the production auto-categorizer: after statement confirmation (including a matched Real-time Claim) it calls TypeSafe Jev and applies a Category when Choice confidence and the evidence Noul are both at least 0.5. A daily in-worker catch-up at 21:00 Asia/Singapore drains leftover `categorization_needed` Reviews, including Wallet-originated Transactions Jev missed. Conversational agents, MCP, and owner-chosen models stay outside Billzebub as in ADR 0003; Jev is a system job with an agent-safe field set, not a chat runtime.

This supersedes the host-side / forge webhook path. The TypeSafe API key lives on rafiki as a mode-`0600` secret the worker already mounts. `scripts/agent/jev_categorize.py` remains an optional ops CLI and is not the production path.

## Consequences

- The worker image includes `typesafe-sdk` and joins the Compose `egress` network solely so it can reach `https://api.typesafe.ai`.
- Missing key, low confidence, skip, or TypeSafe failure leaves the Transaction Uncategorized with `categorization_needed` (fail closed).
- No forge routine, Grok Bot, or webhook is required for production categorization.
