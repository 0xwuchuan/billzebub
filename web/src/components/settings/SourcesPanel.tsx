import { useState, type FormEvent } from "react";

import type { FinancialAccount } from "../../api";
import { formatOwnerCardLabel } from "../../lib/labels";
import { Button } from "../ui/Button";

export function SourcesPanel({
  accounts,
  saving,
  onAddAlias,
  mode = "all",
}: {
  accounts: FinancialAccount[];
  saving: boolean;
  onAddAlias: (accountId: string, cardLabel: string) => Promise<void>;
  mode?: "all" | "list" | "form";
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
      {mode !== "form" ? (
        accounts.length === 0 ? (
          <p className="muted">No Financial Accounts available.</p>
        ) : (
          accounts.map((account) => (
            <div className="account-summary" key={account.id}>
              <span>
                <strong>{account.display_name}</strong>
                <span className="muted">
                  {account.kind === "paylah"
                    ? "Shortcut ingest"
                    : `Inbox ${account.inbox_ready ? "ready" : "missing"}`}
                </span>
              </span>
              <span className="alias-list">
                {account.aliases.length === 0
                  ? "No Wallet alias"
                  : account.aliases
                      .map((alias) => formatOwnerCardLabel(alias.display_label))
                      .join(", ")}
              </span>
            </div>
          ))
        )
      ) : null}
      {mode !== "list" ? (
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
          <p className="muted settings-help">
            This stores the Wallet display label server-side. Statement
            selectors and passwords stay off this page.
          </p>
          <Button
            variant="primary"
            type="submit"
            disabled={saving || cardLabel.trim() === ""}
          >
            {saving ? "Saving…" : "Map Wallet card"}
          </Button>
        </form>
      ) : null}
    </div>
  );
}
