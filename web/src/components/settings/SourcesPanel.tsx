import { useState, type FormEvent } from "react";

import type { FinancialAccount } from "../../api";
import { Button } from "../ui/Button";
import { formatOwnerCardLabel } from "../../lib/labels";

export function SourcesPanel({
  accounts,
  saving,
  onAddAlias,
}: {
  accounts: FinancialAccount[];
  saving: boolean;
  onAddAlias: (accountId: string, cardLabel: string) => Promise<void>;
}) {
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [cardLabel, setCardLabel] = useState("");
  const selected =
    accounts.find((account) => account.id === accountId) ?? accounts[0];

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === undefined || cardLabel.trim() === "") {
      return;
    }
    await onAddAlias(selected.id, cardLabel.trim());
    setCardLabel("");
  }

  return (
    <div className="stack">
      {accounts.map((account) => (
        <div className="card" key={account.id} style={{ padding: "12px 16px" }}>
          <strong>{account.display_name}</strong>
          {account.kind === "paylah" ? (
            <div className="path">Shortcut ingest · no statement inbox</div>
          ) : (
            <div className="path">
              Inbox {account.inbox_ready ? "ready" : "missing"} · password{" "}
              {account.password_configured ? "configured" : "not configured"}
            </div>
          )}
          {account.aliases.length === 0 ? (
            <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
              No Wallet card aliases
            </p>
          ) : (
            account.aliases.map((alias) => (
              <p className="path" key={alias.id}>
                {alias.alias_kind}: {formatOwnerCardLabel(alias.display_label)}
              </p>
            ))
          )}
        </div>
      ))}
      <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
        Statement password files remain NAS mode-0600 secrets. Mapping a Wallet
        card stores the label server-side. Owner lists show the card name and
        last4; full statement selectors stay off this page.
      </p>
      <form className="stack" onSubmit={(event) => void onSubmit(event)}>
        <label className="field-label">
          Financial Account
          <select
            className="select"
            value={selected?.id ?? ""}
            onChange={(event) => {
              setAccountId(event.target.value);
            }}
          >
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Apple Wallet card label
          <input
            className="field"
            value={cardLabel}
            autoComplete="off"
            placeholder="Card name from Wallet"
            onChange={(event) => {
              setCardLabel(event.target.value);
            }}
          />
        </label>
        <Button
          variant="outline"
          type="submit"
          disabled={saving || cardLabel.trim() === ""}
        >
          {saving ? "Saving…" : "Map Wallet card"}
        </Button>
      </form>
    </div>
  );
}
