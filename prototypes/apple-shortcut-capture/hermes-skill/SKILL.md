---
name: billzebub-listener
description: "Check the Billzebub Apple Shortcut listener, inspect recent capture times, or read full captured Wallet payloads."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [billzebub, apple-wallet, listener, captures]
    related_skills: []
---

# Billzebub Apple Shortcut listener

Use the local inspector as the sole interface:

```bash
python /opt/data/scripts/check_billzebub_listener.py
```

The result includes current listener health, total capture count, and the newest full metadata and request body. To inspect more captures:

```bash
# Five newest captures
python /opt/data/scripts/check_billzebub_listener.py --limit 5

# Every retained capture
python /opt/data/scripts/check_billzebub_listener.py --limit 0

# Captures strictly after an RFC 3339 instant
python /opt/data/scripts/check_billzebub_listener.py --since 2026-08-27T11:13:26Z --limit 0
```

Report capture timestamps in SGT using `received_at_sgt`. Distinguish raw captures from trusted Billzebub Transactions. A healthy listener with no newer capture means the request did not reach the capture module. Keep captured financial content within the user's current conversation and local NAS.
