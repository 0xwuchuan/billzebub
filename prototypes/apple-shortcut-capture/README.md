# Apple Shortcut capture prototype

> **THROWAWAY PROTOTYPE.** This exists only to discover what the Wallet transaction automation can deliver. Captured financial data belongs in `runtime/`, which is ignored by Git, and must not be committed.

## NAS deployment

The probe currently runs on the Synology NAS as `billzebub-apple-shortcut-probe`, with restart policy `unless-stopped`. Tailscale Serve exposes it only within the Tailnet at:

```text
https://rafiki.tail7c684e.ts.net/capture
```

The deployment lives outside the repository at `/volume1/docker/billzebub-apple-shortcut-probe/`. Captures and the bearer token are stored in its mode-700 `runtime/` directory. Capture files use the dedicated numeric group `19999`; the local `hermes` container joins that group and mounts only `runtime/captures/` read-only. The token remains inaccessible to Hermes.

Check it from this Mac:

```bash
curl https://rafiki.tail7c684e.ts.net/health
ssh wuchuan@rafiki.tail7c684e.ts.net \
  '/usr/local/bin/docker inspect --format "{{.State.Status}}/{{.State.Health.Status}}" billzebub-apple-shortcut-probe'
```

Inspect the newest capture without copying it off the NAS:

```bash
ssh wuchuan@rafiki.tail7c684e.ts.net \
  'cd /volume1/docker/billzebub-apple-shortcut-probe && python3 inspect_capture.py'
```

The local Hermes agent can inspect health and full captured payloads through its narrow read-only access:

```bash
docker exec hermes python /opt/data/scripts/check_billzebub_listener.py
```

Hermes reaches health internally at `http://billzebub-apple-shortcut-probe:8765/health` and reads captures from `/opt/billzebub-listener/captures`. It has neither the ingestion token nor Docker socket access.

Remove the deployment after the experiment:

```bash
ssh wuchuan@rafiki.tail7c684e.ts.net \
  'cd /volume1/docker/billzebub-apple-shortcut-probe && /usr/local/bin/docker compose down && /usr/local/bin/tailscale serve reset'
```

## Initial experiment

The first experiment is deliberately schema-free:

1. In the existing **Transaction → When I tap** automation, choose **Create New Shortcut** and add **Get Contents of URL**.
2. Set the URL to the Tailnet URL ending in `/capture`.
3. Set method to `POST`.
4. Add the `Authorization` header whose bearer value is stored in the NAS deployment's `runtime/token`.
5. In the reliable first request, map the exposed **Shortcut Input** details—Name, Card, Merchant, and Amount—along with Current Date. The entire Shortcut Input may be converted to text only in an optional second request, after the reliable request succeeds.
6. Add **Show Notification** after each HTTP action so success or failure is visible during the experiment.

The experiment must answer:

- Does the transaction trigger expose any input at all?
- If so, what type and detail fields are available?
- Does a tap trigger before authorization, after authorization, or for non-payment passes too?
- Does the automation run with the phone locked?
- What happens when Tailscale or the receiver is unavailable?
- Can one tap invoke more than once?
