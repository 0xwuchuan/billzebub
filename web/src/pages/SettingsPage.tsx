import type {
  Category,
  CreateFinancialAccountInput,
  FinancialAccount,
  IssuedToken,
  IntegrationToken,
  OwnerIdentity,
  StatementAdapter,
  StatementCoverageReport,
} from "../api";
import { AccountsPanel } from "../components/settings/AccountsPanel";
import { CategoriesPanel } from "../components/settings/CategoriesPanel";
import { SourcesPanel } from "../components/settings/SourcesPanel";
import { StatementCoveragePanel } from "../components/StatementCoveragePanel";
import { TokensPanel } from "../components/settings/TokensPanel";
import { useEntrance } from "../hooks/useEntrance";

export function SettingsPage({
  identity,
  accounts,
  adapters,
  categories,
  tokens,
  issuedToken,
  coverage,
  saving,
  onCreateAccount,
  onAddAlias,
  onCreateCategory,
  onIssueToken,
  onRotateToken,
  onRevokeToken,
  onDismissIssuedToken,
  onOpenAccountImports,
}: {
  identity: OwnerIdentity | null;
  accounts: FinancialAccount[];
  adapters: StatementAdapter[];
  categories: Category[];
  tokens: IntegrationToken[];
  issuedToken: IssuedToken | null;
  coverage: StatementCoverageReport | null;
  saving: string | null;
  onCreateAccount: (input: CreateFinancialAccountInput) => Promise<void>;
  onAddAlias: (accountId: string, cardLabel: string) => Promise<void>;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
  onOpenAccountImports: (accountId: string) => void;
}) {
  const fresh = useEntrance("settings");
  const inboxReady = accounts.filter(
    (account) => account.kind !== "paylah" && account.inbox_ready,
  ).length;
  const inboxNeeded = accounts.filter(
    (account) => account.kind !== "paylah",
  ).length;
  return (
    <div className={`settings${fresh ? " stage-enter" : ""}`}>
      <section className="card settings-section">
        <h2>Workspace</h2>
        <dl className="kv">
          <dt>Owner identity</dt>
          <dd>{identity?.login ?? "waiting for Tailscale…"}</dd>
          <dt>Reporting Currency</dt>
          <dd>SGD · Asia/Singapore</dd>
          <dt>Inbox readiness</dt>
          <dd>
            {inboxNeeded === 0
              ? "No statement inboxes yet"
              : `${inboxReady} of ${inboxNeeded} credit-card inboxes ready`}
          </dd>
        </dl>
      </section>
      <section className="card settings-section">
        <h2>Financial Accounts</h2>
        <AccountsPanel
          accounts={accounts}
          adapters={adapters}
          saving={saving === "account"}
          onCreateAccount={onCreateAccount}
        />
      </section>
      <StatementCoveragePanel
        coverage={coverage}
        selectedAccountId={null}
        onSelectAccount={onOpenAccountImports}
      />
      <section className="card settings-section">
        <h2>Wallet aliases</h2>
        <SourcesPanel
          accounts={accounts}
          saving={saving === "alias"}
          onAddAlias={onAddAlias}
        />
      </section>
      <section className="card settings-section">
        <h2>Categories</h2>
        <CategoriesPanel
          categories={categories}
          saving={saving === "category"}
          onCreateCategory={onCreateCategory}
        />
      </section>
      <section className="card settings-section">
        <h2>Shortcut tokens</h2>
        <TokensPanel
          tokens={tokens}
          issuedToken={issuedToken}
          saving={saving}
          onIssueToken={onIssueToken}
          onRotateToken={onRotateToken}
          onRevokeToken={onRevokeToken}
          onDismissIssuedToken={onDismissIssuedToken}
        />
      </section>
    </div>
  );
}
