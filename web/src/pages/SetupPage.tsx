import { useState, type Dispatch, type FormEvent } from "react";

import type {
  Category,
  CreateFinancialAccountInput,
  FinancialAccount,
  IssuedToken,
  IntegrationToken,
  OwnerIdentity,
  StatementAdapter,
} from "../api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { SETUP_ACCOUNT_EXAMPLES, SETUP_CATEGORIES } from "../lib/accounts";
import {
  SETUP_STEP_COUNT,
  SETUP_STEPS,
  firstBlockedStep,
  stepIndexValid,
  type SetupAction,
  type SetupGates,
  type SetupState,
} from "../lib/setup";

export function SetupPage({
  state,
  dispatch,
  gates,
  identity,
  accounts,
  adapters,
  categories,
  tokens,
  issuedToken,
  saving,
  transactionCount,
  reviewCount,
  blockingCount,
  onCreateAccount,
  onAddAlias,
  onCreateCategory,
  onIssueToken,
  onRotateToken,
  onRevokeToken,
  onDismissIssuedToken,
  onReturn,
}: {
  state: SetupState;
  dispatch: Dispatch<SetupAction>;
  gates: SetupGates;
  identity: OwnerIdentity | null;
  accounts: FinancialAccount[];
  adapters: StatementAdapter[];
  categories: Category[];
  tokens: IntegrationToken[];
  issuedToken: IssuedToken | null;
  saving: string | null;
  transactionCount: number;
  reviewCount: number;
  blockingCount: number;
  onCreateAccount: (input: CreateFinancialAccountInput) => Promise<void>;
  onAddAlias: (accountId: string, cardLabel: string) => Promise<void>;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
  onReturn: () => void;
}) {
  const index = state.step;
  const step = SETUP_STEPS[index];
  const blocked = firstBlockedStep(state, gates);
  const valid = stepIndexValid(index, gates);
  const last = index === SETUP_STEP_COUNT - 1;
  const replay = index === 0 && state.onboarded;
  const fresh = useEntrance(`onboarding:${index}`);
  if (step === undefined) {
    return null;
  }
  return (
    <div className="app is-onboarding">
      <div className="onboard">
        <article className={`card onboard-card${fresh ? " stage-enter" : ""}`}>
          <p className="eyebrow">
            Setup · {index + 1} of {SETUP_STEP_COUNT}
          </p>
          <div className="steps" role="list">
            {SETUP_STEPS.map((item, stepIndex) => (
              <button
                key={item.id}
                className={`step-dot${stepIndex < index ? " is-done" : ""}`}
                type="button"
                aria-label={item.id}
                aria-current={stepIndex === index ? "step" : undefined}
                disabled={stepIndex > blocked}
                onClick={() => {
                  dispatch({ type: "goStep", step: stepIndex });
                }}
              />
            ))}
          </div>
          <h1>{step.title}</h1>
          <p className="lede">{step.lede}</p>
          <StepBody
            state={state}
            identity={identity}
            accounts={accounts}
            adapters={adapters}
            categories={categories}
            tokens={tokens}
            issuedToken={issuedToken}
            saving={saving}
            transactionCount={transactionCount}
            reviewCount={reviewCount}
            blockingCount={blockingCount}
            onCreateAccount={onCreateAccount}
            onAddAlias={onAddAlias}
            onCreateCategory={onCreateCategory}
            onIssueToken={onIssueToken}
            onRotateToken={onRotateToken}
            onRevokeToken={onRevokeToken}
            onDismissIssuedToken={onDismissIssuedToken}
          />
          <div className="onboard-nav">
            {replay ? (
              <Button variant="ghost" onClick={onReturn}>
                Return to Overview
              </Button>
            ) : (
              <Button
                variant="ghost"
                disabled={index === 0}
                onClick={() => {
                  dispatch({ type: "back" });
                }}
              >
                Back
              </Button>
            )}
            <div className="onboard-nav-actions">
              <p className="gate-hint" role="status" hidden={valid}>
                {step.hint}
              </p>
              <Button
                variant="primary"
                disabled={!valid}
                onClick={() => {
                  if (last) {
                    dispatch({ type: "finish" });
                    onReturn();
                    return;
                  }
                  dispatch({ type: "advance" });
                }}
              >
                {last ? "Enter Overview" : "Continue"}
              </Button>
            </div>
          </div>
        </article>
      </div>
    </div>
  );
}

function StepBody({
  state,
  identity,
  accounts,
  adapters,
  categories,
  tokens,
  issuedToken,
  saving,
  transactionCount,
  reviewCount,
  blockingCount,
  onCreateAccount,
  onAddAlias,
  onCreateCategory,
  onIssueToken,
  onRotateToken,
  onRevokeToken,
  onDismissIssuedToken,
}: {
  state: SetupState;
  identity: OwnerIdentity | null;
  accounts: FinancialAccount[];
  adapters: StatementAdapter[];
  categories: Category[];
  tokens: IntegrationToken[];
  issuedToken: IssuedToken | null;
  saving: string | null;
  transactionCount: number;
  reviewCount: number;
  blockingCount: number;
  onCreateAccount: (input: CreateFinancialAccountInput) => Promise<void>;
  onAddAlias: (accountId: string, cardLabel: string) => Promise<void>;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
}) {
  if (state.step === 0) {
    return (
      <div className="stack">
        <label className="field-label">
          Reporting Currency
          <input className="field" value="SGD" readOnly />
        </label>
        <label className="field-label">
          Timezone
          <input className="field" value="Asia/Singapore" readOnly />
        </label>
        <label className="field-label">
          Owner identity
          <input
            className="field"
            value={identity?.login ?? "waiting for Tailscale…"}
            readOnly
          />
        </label>
        <p className="muted">
          Owner identity comes from Tailscale. Statement passwords stay in
          mode-0600 NAS files. This flow never stores secrets in the browser.
        </p>
      </div>
    );
  }
  if (state.step === 1) {
    return (
      <AccountsStep
        accounts={accounts}
        adapters={adapters}
        saving={saving === "account"}
        onCreateAccount={onCreateAccount}
      />
    );
  }
  if (state.step === 2) {
    return (
      <SourcesStep
        accounts={accounts}
        tokens={tokens}
        issuedToken={issuedToken}
        saving={saving}
        onAddAlias={onAddAlias}
        onIssueToken={onIssueToken}
        onRotateToken={onRotateToken}
        onRevokeToken={onRevokeToken}
        onDismissIssuedToken={onDismissIssuedToken}
      />
    );
  }
  if (state.step === 3) {
    return (
      <CategoriesStep
        categories={categories}
        saving={saving === "category"}
        onCreateCategory={onCreateCategory}
      />
    );
  }
  const ownerCategories = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  return (
    <div className="stack">
      <dl className="kv">
        <dt>Financial Accounts</dt>
        <dd>{accounts.length} watching, Reporting Currency SGD</dd>
        <dt>Categories</dt>
        <dd>{ownerCategories.length} enabled for Expense reporting</dd>
        <dt>Apple Shortcut</dt>
        <dd>
          {tokens.length > 0
            ? `${tokens.length} scoped token${tokens.length === 1 ? "" : "s"}`
            : "No Shortcut token yet"}
        </dd>
        <dt>Transactions</dt>
        <dd>{transactionCount} established</dd>
        <dt>Pending Review</dt>
        <dd>
          {reviewCount} items
          {blockingCount > 0 ? ", including Blocking items" : ""}
        </dd>
        <dt>Next</dt>
        <dd>Overview is home. The rail badge keeps Review one click away.</dd>
      </dl>
    </div>
  );
}

function AccountsStep({
  accounts,
  adapters,
  saving,
  onCreateAccount,
}: {
  accounts: FinancialAccount[];
  adapters: StatementAdapter[];
  saving: boolean;
  onCreateAccount: (input: CreateFinancialAccountInput) => Promise<void>;
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
      {accounts.length === 0 ? (
        <p className="muted">No Financial Accounts yet.</p>
      ) : (
        accounts.map((account) => (
          <div className="card account-toggle" key={account.id}>
            <Badge tone={account.active ? "confirmed" : "count"}>
              {account.kind === "paylah" ? "PayLah" : "Credit card"}
            </Badge>
            <span>
              <strong style={{ display: "block" }}>
                {account.display_name}
              </strong>
              <span className="muted">
                {account.slug} · {account.institution}
              </span>
            </span>
          </div>
        ))
      )}
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
              const next =
                event.target.value === "paylah" ? "paylah" : "credit_card";
              setKind(next);
            }}
          >
            <option value="credit_card">credit_card</option>
            <option value="paylah">paylah</option>
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
            <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
              The filename is a reference only. Create the mode-0600 file on the
              NAS first; Billzebub will not accept the password itself here.
            </p>
          </>
        ) : (
          <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
            PayLah uses Shortcut ingest, not a statement inbox or mailbox
            secret. Keep a single active paylah Financial Account.
          </p>
        )}
        <Button variant="primary" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Create Financial Account"}
        </Button>
      </form>
    </div>
  );
}

function SourcesStep({
  accounts,
  tokens,
  issuedToken,
  saving,
  onAddAlias,
  onIssueToken,
  onRotateToken,
  onRevokeToken,
  onDismissIssuedToken,
}: {
  accounts: FinancialAccount[];
  tokens: IntegrationToken[];
  issuedToken: IssuedToken | null;
  saving: string | null;
  onAddAlias: (accountId: string, cardLabel: string) => Promise<void>;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
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
                {alias.alias_kind}: {alias.masked_value}
              </p>
            ))
          )}
        </div>
      ))}
      <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
        Statement password files remain NAS mode-0600 secrets. Mapping a Wallet
        card stores the label server-side and lists only a masked value here.
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
          disabled={saving === "alias" || cardLabel.trim() === ""}
        >
          {saving === "alias" ? "Saving…" : "Map Wallet card"}
        </Button>
      </form>
      <div className="card" style={{ padding: "12px 16px" }}>
        <strong>Shortcut integration token</strong>
        <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
          Scope shortcut:claims:create. Plaintext is shown once and is not
          written to localStorage.
        </p>
        {tokens.map((token) => (
          <div key={token.id} className="token-row">
            <span>
              {token.name} · {token.prefix}
            </span>
            <span className="onboard-nav-actions">
              <Button
                variant="outline"
                disabled={saving === token.id}
                onClick={() => {
                  void onRotateToken(token.id);
                }}
              >
                Rotate
              </Button>
              <Button
                variant="ghost"
                disabled={saving === token.id}
                onClick={() => {
                  void onRevokeToken(token.id);
                }}
              >
                Revoke
              </Button>
            </span>
          </div>
        ))}
        <Button
          variant="outline"
          disabled={saving === "token"}
          onClick={() => {
            void onIssueToken();
          }}
        >
          {saving === "token" ? "Issuing…" : "Issue Shortcut token"}
        </Button>
        {issuedToken !== null ? (
          <div className="probe">
            <p className="probe-line">
              Copy this token now. It will not be shown again.
            </p>
            <code className="path">{issuedToken.plaintext}</code>
            <Button variant="ghost" onClick={onDismissIssuedToken}>
              Hide token
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CategoriesStep({
  categories,
  saving,
  onCreateCategory,
}: {
  categories: Category[];
  saving: boolean;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const ownerCategories = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  const parents = ownerCategories.filter(
    (category) => category.parent_id === null,
  );
  const suggested = SETUP_CATEGORIES.filter(
    (item) =>
      !ownerCategories.some(
        (category) => category.name.toLowerCase() === item.toLowerCase(),
      ),
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "") {
      return;
    }
    await onCreateCategory(name.trim(), parentId === "" ? undefined : parentId);
    setName("");
  }

  return (
    <div className="stack">
      <div className="filters">
        {ownerCategories.map((category) => (
          <span className="chip" aria-pressed="true" key={category.id}>
            {category.parent_id === null
              ? category.name
              : `${parents.find((parent) => parent.id === category.parent_id)?.name ?? ""} / ${category.name}`}
          </span>
        ))}
        <span className="chip">Uncategorized</span>
      </div>
      {suggested.length > 0 ? (
        <div className="filters">
          {suggested.map((item) => (
            <button
              key={item}
              className="chip"
              type="button"
              disabled={saving}
              onClick={() => {
                void onCreateCategory(item);
              }}
            >
              Add {item}
            </button>
          ))}
        </div>
      ) : null}
      <form className="stack" onSubmit={(event) => void onSubmit(event)}>
        <label className="field-label">
          Add a Category
          <input
            className="field"
            value={name}
            placeholder="Family, Pets, Home"
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <label className="field-label">
          Parent (optional subcategory)
          <select
            className="select"
            value={parentId}
            onChange={(event) => {
              setParentId(event.target.value);
            }}
          >
            <option value="">Top-level</option>
            {parents.map((parent) => (
              <option key={parent.id} value={parent.id}>
                {parent.name}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="primary"
          type="submit"
          disabled={saving || name.trim() === ""}
        >
          {saving ? "Saving…" : "Create Category"}
        </Button>
      </form>
    </div>
  );
}
