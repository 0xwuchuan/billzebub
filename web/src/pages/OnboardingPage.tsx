import { type Dispatch } from "react";

import type {
  Category,
  CreateFinancialAccountInput,
  FinancialAccount,
  IssuedToken,
  IntegrationToken,
  OwnerIdentity,
  StatementAdapter,
} from "../api";
import { Button } from "../components/ui/Button";
import { AccountsPanel } from "../components/settings/AccountsPanel";
import { CategoriesPanel } from "../components/settings/CategoriesPanel";
import { SourcesPanel } from "../components/settings/SourcesPanel";
import { TokensPanel } from "../components/settings/TokensPanel";
import { useEntrance } from "../hooks/useEntrance";
import {
  ONBOARDING_STEP_COUNT,
  ONBOARDING_STEPS,
  firstBlockedStep,
  stepIndexValid,
  type SetupAction,
  type SetupGates,
  type SetupState,
} from "../lib/setup";

export function OnboardingPage({
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
  const step = ONBOARDING_STEPS[index];
  const blocked = firstBlockedStep(state, gates);
  const valid = stepIndexValid(index, gates);
  const last = index === ONBOARDING_STEP_COUNT - 1;
  const fresh = useEntrance(`onboarding:${index}`);
  if (step === undefined) {
    return null;
  }
  return (
    <div className="app is-onboarding">
      <div className="onboard">
        <article className={`card onboard-card${fresh ? " stage-enter" : ""}`}>
          <p className="eyebrow">
            Onboarding · {index + 1} of {ONBOARDING_STEP_COUNT}
          </p>
          <div className="steps" role="list">
            {ONBOARDING_STEPS.map((item, stepIndex) => (
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
            <Button
              variant="ghost"
              disabled={index === 0}
              onClick={() => {
                dispatch({ type: "back" });
              }}
            >
              Back
            </Button>
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
      <AccountsPanel
        accounts={accounts}
        adapters={adapters}
        saving={saving === "account"}
        onCreateAccount={onCreateAccount}
      />
    );
  }
  if (state.step === 2) {
    return (
      <div className="stack">
        <SourcesPanel
          accounts={accounts}
          saving={saving === "alias"}
          onAddAlias={onAddAlias}
        />
        <div className="card" style={{ padding: "12px 16px" }}>
          <strong>Shortcut integration token</strong>
          <TokensPanel
            tokens={tokens}
            issuedToken={issuedToken}
            saving={saving}
            onIssueToken={onIssueToken}
            onRotateToken={onRotateToken}
            onRevokeToken={onRevokeToken}
            onDismissIssuedToken={onDismissIssuedToken}
          />
        </div>
      </div>
    );
  }
  if (state.step === 3) {
    return (
      <CategoriesPanel
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
        <dd>Overview is home. Settings keeps accounts, aliases, and tokens.</dd>
      </dl>
    </div>
  );
}
