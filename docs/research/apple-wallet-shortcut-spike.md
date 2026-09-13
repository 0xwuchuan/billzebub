# Apple Wallet Shortcut ingestion spike

## Question

Can an iPhone Wallet **Transaction → When I tap** automation deliver useful Real-time Claim data automatically to a locally hosted Billzebub endpoint?

## Confirmed so far

- A Shortcut running as `BackgroundShortcutRunner` can send an authenticated JSON `POST` through Tailscale without opening Billzebub.
- The user's iOS Shortcuts build exposes Wallet Transaction input details for Name, Card, Merchant, and Amount. The whole Shortcut Input can also be offered to a separate best-effort text conversion after the reliable field request.
- A physical event produced the complete `probe-2` JSON shape: `schema_version`, `name`, `merchant`, `card`, `amount`, and `date`, all text. Card and merchant are populated on the current full request.
- Amount is dollar-prefixed text. Date is a local English abbreviated-month timestamp with no offset. Production parses those exact formats strictly, assigns currency from the locally mapped Financial Account, and applies the owner-configured IANA timezone; it does not infer either from the payload.
- A Transaction automation cannot be meaningfully run from the editor because real Shortcut Input exists only when Wallet emits an actual transaction event.
- The native action set did not expose a Generate UUID action. Production deduplicates exact retry bodies by their Source Artifact hash while retaining each arrival.
- A Tailnet-only HTTPS receiver is running on the Synology NAS at `https://rafiki.tail7c684e.ts.net/capture`. Its container restarts unless stopped, and captured bodies remain under `/volume1/docker/billzebub-apple-shortcut-probe/runtime/`.
- The Mac receiver has been stopped and is not required.

## Pending real-world observation

The next physical Apple Pay purchase must establish:

- Whether the whole Shortcut Input converts to useful text beyond the reliable structured request.
- Whether an Apple event generated while travelling is expressed in the configured owner timezone or the device's current timezone.
- Trigger and receiver timestamps.
- Whether both configured requests execute while the phone is locked.
- Whether one Wallet event causes duplicate delivery.
- Failure behavior when Tailscale or Billzebub is unavailable.

No captured financial payloads belong in Git. The probe implementation is explicitly throwaway and should be removed after its findings are folded into the production ingestion contract.
