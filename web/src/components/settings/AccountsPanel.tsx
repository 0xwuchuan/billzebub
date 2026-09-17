import { useState, type FormEvent } from "react";

import type {
  CreateFinancialAccountInput,
  FinancialAccount,
  StatementAdapter,
} from "../../api";
import { SETUP_ACCOUNT_EXAMPLES } from "../../lib/accounts";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";

export function AccountsPanel({
  accounts,
  adapters,
  saving,
  onCreateAccount,
  mode = "all",
}: {
  accounts: FinancialAccount[];
  adapters: StatementAdapter[];
  saving: boolean;
  onCreateAccount: (input: CreateFinancialAccountInput) => Promise<void>;
  mode?: "all" | "list" | "form";
}) {
  const [kind, setKind] = useState<"credit_card" | "paylah">("credit_card");
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [adapterKey, setAdapterKey] = useState(adapters[0]?.key ?? "");
  const [identifier, setIdentifier] = useState("");
  const [secretName, setSecretName] = useState("");
  const selectedAdapter = adapters.find(
    (adapter) => adapter.key === adapterKey,
  );
  const suggestedAccounts = SETUP_ACCOUNT_EXAMPLES.filter(
    (example) => !accounts.some((account) => account.slug === example.slug),
  );

  function applyExample(example: (typeof SETUP_ACCOUNT_EXAMPLES)[number]) {
    const adapter =
      adapters.find((item) => item.institution === example.institution) ??
      adapters[0];
    setKind("credit_card");
    setSlug(example.slug);
    setDisplayName(example.displayName);
    setAdapterKey(adapter?.key ?? "");
    setSecretName(`${example.slug}.password`);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input: CreateFinancialAccountInput = {
      slug: slug.trim(),
      display_name: displayName.trim(),
      institution:
        kind === "credit_card"
          ? (selectedAdapter?.institution ?? "dbs")
          : "dbs",
      kind,
      default_currency: "SGD",
    };
    if (kind === "credit_card") {
      input.statement_adapter_key = adapterKey;
      input.statement_account_identifier = identifier.trim();
      if (secretName.trim() !== "") {
        input.statement_password_secret = secretName.trim();
      }
    }
    await onCreateAccount(input);
    setSlug("");
    setDisplayName("");
    setIdentifier("");
    setSecretName("");
  }

  return (
    <div className="stack">
      {mode !== "form" ? (
        accounts.length === 0 ? (
          <p className="muted">No Financial Accounts yet.</p>
        ) : (
          accounts.map((account) => (
            <div className="account-summary" key={account.id}>
              <span>
                <strong>{account.display_name}</strong>
                <span className="muted">
                  {account.institution} · {account.default_currency}
                </span>
              </span>
              <Badge tone={account.active ? "confirmed" : "count"}>
                {account.kind === "paylah" ? "PayLah" : "Credit card"}
              </Badge>
            </div>
          ))
        )
      ) : null}
      {mode !== "list" ? (
        <>
          {suggestedAccounts.length > 0 ? (
            <div className="filters">
              {suggestedAccounts.map((example) => (
                <button
                  key={example.slug}
                  className="chip"
                  type="button"
                  onClick={() => {
                    applyExample(example);
                  }}
                >
                  {example.displayName}
                </button>
              ))}
            </div>
          ) : null}
          <form className="stack" onSubmit={(event) => void onSubmit(event)}>
            <label className="field-label">
              Kind
              <select
                className="select"
                value={kind}
                onChange={(event) => {
                  setKind(
                    event.target.value === "paylah" ? "paylah" : "credit_card",
                  );
                }}
              >
                <option value="credit_card">Credit card</option>
                <option value="paylah">PayLah</option>
              </select>
            </label>
            <label className="field-label">
              Slug
              <input
                className="field"
                value={slug}
                required
                placeholder="dbs-live-fresh"
                onChange={(event) => {
                  setSlug(event.target.value);
                }}
              />
            </label>
            <label className="field-label">
              Display name
              <input
                className="field"
                value={displayName}
                required
                placeholder="DBS Live Fresh"
                onChange={(event) => {
                  setDisplayName(event.target.value);
                }}
              />
            </label>
            {kind === "credit_card" ? (
              <>
                <label className="field-label">
                  Statement adapter
                  <select
                    className="select"
                    value={adapterKey}
                    onChange={(event) => {
                      setAdapterKey(event.target.value);
                    }}
                  >
                    {adapters.map((adapter) => (
                      <option key={adapter.key} value={adapter.key}>
                        {adapter.key}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-label">
                  Statement account identifier
                  <input
                    className="field"
                    value={identifier}
                    required
                    autoComplete="off"
                    onChange={(event) => {
                      setIdentifier(event.target.value);
                    }}
                  />
                </label>
                <label className="field-label">
                  Password secret filename (optional)
                  <input
                    className="field"
                    value={secretName}
                    placeholder="dbs-live-fresh.password"
                    autoComplete="off"
                    onChange={(event) => {
                      setSecretName(event.target.value);
                    }}
                  />
                </label>
                <p className="muted settings-help">
                  Reference the mode-0600 NAS file only. Never enter the
                  password itself here.
                </p>
              </>
            ) : (
              <p className="muted settings-help">
                PayLah uses Shortcut ingest and does not need a statement inbox.
              </p>
            )}
            <Button variant="primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Create Financial Account"}
            </Button>
          </form>
        </>
      ) : null}
    </div>
  );
}
