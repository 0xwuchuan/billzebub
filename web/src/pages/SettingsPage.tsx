import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type {
  Category,
  CreateFinancialAccountInput,
  FinancialAccount,
  IssuedToken,
  IntegrationToken,
  OwnerIdentity,
  StatementAdapter,
  StatementCoverageReport,
  Transaction,
} from "../api";
import type { CategoryPatch } from "../components/settings/CategoriesPanel";
import { StatementCoveragePanel } from "../components/StatementCoveragePanel";
import { ThemeToggle } from "../components/ThemeToggle";
import { AccountsPanel } from "../components/settings/AccountsPanel";
import { CategoriesPanel } from "../components/settings/CategoriesPanel";
import { SourcesPanel } from "../components/settings/SourcesPanel";
import { TokensPanel } from "../components/settings/TokensPanel";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import type { Theme } from "../lib/theme";

type SettingsModal = "account" | "alias" | "category" | "token";

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
  transactions = [],
  month,
  onCreateCategory,
  onUpdateCategory,
  onIssueToken,
  onRotateToken,
  onRevokeToken,
  onDismissIssuedToken,
  onOpenAccountImports,
  theme,
  onToggleTheme,
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
  transactions?: Transaction[] | undefined;
  month?: string | undefined;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  onUpdateCategory?:
    ((category: Category, patch: CategoryPatch) => Promise<void>) | undefined;
  onIssueToken: () => Promise<void>;
  onRotateToken: (tokenId: string) => Promise<void>;
  onRevokeToken: (tokenId: string) => Promise<void>;
  onDismissIssuedToken: () => void;
  onOpenAccountImports: (accountId: string) => void;
  theme: Theme;
  onToggleTheme: () => void;
}) {
  const fresh = useEntrance("settings");
  const [modal, setModal] = useState<SettingsModal | null>(null);
  const inboxReady = accounts.filter(
    (account) => account.kind !== "paylah" && account.inbox_ready,
  ).length;
  const inboxNeeded = accounts.filter(
    (account) => account.kind !== "paylah",
  ).length;
  const ownerCategories = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );

  return (
    <div className={`settings${fresh ? " stage-enter" : ""}`}>
      <section className="card settings-section settings-workspace">
        <div>
          <p className="eyebrow">Workspace</p>
          <h2>{identity?.login ?? "Local owner"}</h2>
        </div>
        <dl className="settings-facts">
          <div>
            <dt>Currency</dt>
            <dd>SGD</dd>
          </div>
          <div>
            <dt>Timezone</dt>
            <dd>Asia/Singapore</dd>
          </div>
          <div>
            <dt>Statement inboxes</dt>
            <dd>
              {inboxNeeded === 0
                ? "None yet"
                : `${inboxReady} of ${inboxNeeded} ready`}
            </dd>
          </div>
        </dl>
      </section>

      <section className="card settings-section settings-appearance">
        <div className="theme-row">
          <div>
            <h2>Appearance</h2>
            <p className="muted">
              {theme === "dark" ? "Dark" : "Light"} theme. Saved on this
              machine.
              <span className="settings-theme-phone">
                {" "}
                Switch it from the top bar.
              </span>
            </p>
          </div>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </section>

      <div className="settings-grid">
        <SettingsSection
          title="Financial Accounts"
          count={accounts.length}
          action="Add account"
          onAction={() => {
            setModal("account");
          }}
        >
          <AccountsPanel
            accounts={accounts}
            adapters={adapters}
            saving={saving === "account"}
            onCreateAccount={onCreateAccount}
            mode="list"
          />
        </SettingsSection>

        <SettingsSection
          title="Wallet aliases"
          count={accounts.reduce(
            (sum, account) => sum + account.aliases.length,
            0,
          )}
          action="Map card"
          onAction={() => {
            setModal("alias");
          }}
        >
          <SourcesPanel
            accounts={accounts}
            saving={saving === "alias"}
            onAddAlias={onAddAlias}
            mode="list"
          />
        </SettingsSection>

        <SettingsSection
          title="Categories"
          count={ownerCategories.length}
          action="Add Category"
          onAction={() => {
            setModal("category");
          }}
        >
          <CategoriesPanel
            categories={categories}
            transactions={transactions}
            month={month}
            saving={saving === "category"}
            onCreateCategory={onCreateCategory}
            onUpdateCategory={onUpdateCategory}
            mode="list"
          />
        </SettingsSection>

        <SettingsSection
          title="Shortcut tokens"
          count={tokens.length}
          action="Issue token"
          onAction={() => {
            setModal("token");
          }}
        >
          <TokensPanel
            tokens={tokens}
            issuedToken={issuedToken}
            saving={saving}
            onIssueToken={onIssueToken}
            onRotateToken={onRotateToken}
            onRevokeToken={onRevokeToken}
            onDismissIssuedToken={onDismissIssuedToken}
            mode="list"
          />
        </SettingsSection>
      </div>

      <StatementCoveragePanel
        coverage={coverage}
        selectedAccountId={null}
        onSelectAccount={onOpenAccountImports}
      />

      {modal !== null ? (
        <SettingsDialog
          title={modalTitle(modal)}
          onClose={() => {
            setModal(null);
          }}
        >
          {modal === "account" ? (
            <AccountsPanel
              accounts={accounts}
              adapters={adapters}
              saving={saving === "account"}
              onCreateAccount={async (input) => {
                await onCreateAccount(input);
                setModal(null);
              }}
              mode="form"
            />
          ) : null}
          {modal === "alias" ? (
            <SourcesPanel
              accounts={accounts}
              saving={saving === "alias"}
              onAddAlias={async (accountId, cardLabel) => {
                await onAddAlias(accountId, cardLabel);
                setModal(null);
              }}
              mode="form"
            />
          ) : null}
          {modal === "category" ? (
            <CategoriesPanel
              categories={categories}
              saving={saving === "category"}
              transactions={transactions}
              month={month}
              onCreateCategory={async (name, parentId) => {
                await onCreateCategory(name, parentId);
                setModal(null);
              }}
              onUpdateCategory={onUpdateCategory}
              mode="form"
            />
          ) : null}
          {modal === "token" ? (
            <TokensPanel
              tokens={tokens}
              issuedToken={issuedToken}
              saving={saving}
              onIssueToken={onIssueToken}
              onRotateToken={onRotateToken}
              onRevokeToken={onRevokeToken}
              onDismissIssuedToken={onDismissIssuedToken}
              mode="issue"
            />
          ) : null}
        </SettingsDialog>
      ) : null}
    </div>
  );
}

function SettingsSection({
  title,
  count,
  action,
  onAction,
  children,
}: {
  title: string;
  count: number;
  action: string;
  onAction: () => void;
  children: ReactNode;
}) {
  return (
    <section className="card settings-section">
      <div className="settings-section-head">
        <div>
          <h2>{title}</h2>
          <span className="muted">
            {count} {count === 1 ? "item" : "items"}
          </span>
        </div>
        <Button variant="outline" onClick={onAction}>
          {action}
        </Button>
      </div>
      {children}
    </section>
  );
}

function SettingsDialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null || dialog.open) {
      return;
    }
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }, []);

  function close() {
    const dialog = dialogRef.current;
    if (dialog !== null && typeof dialog.close === "function") {
      dialog.close();
      return;
    }
    onClose();
  }

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog"
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          close();
        }
      }}
    >
      <div className="settings-dialog-head">
        <div>
          <p className="eyebrow">Settings</p>
          <h2 id={titleId}>{title}</h2>
        </div>
        <Button variant="ghost" onClick={close}>
          Close
        </Button>
      </div>
      <div className="settings-dialog-body">{children}</div>
    </dialog>
  );
}

function modalTitle(modal: SettingsModal): string {
  if (modal === "account") {
    return "Add Financial Account";
  }
  if (modal === "alias") {
    return "Map Wallet card";
  }
  if (modal === "category") {
    return "Add Category";
  }
  return "Issue Shortcut token";
}
