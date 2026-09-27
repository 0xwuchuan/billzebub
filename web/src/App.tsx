import { useEffect, useMemo, useState } from "react";

import type { Transaction } from "./api";
import { AppShell } from "./components/AppShell";
import { TransactionDrawer } from "./components/TransactionDrawer";
import { useRoute } from "./hooks/useRoute";
import { useSetup } from "./hooks/useSetup";
import { useTheme } from "./hooks/useTheme";
import { useWorkspace } from "./hooks/useWorkspace";
import { isoDate, monthYearLabel } from "./lib/labels";
import {
  emptyRoute,
  type ConfirmationFilter,
  type ReviewFilter,
  type Route,
} from "./lib/route";
import { gatesMet } from "./lib/setup";
import { ImportsPage } from "./pages/ImportsPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SpendingPage } from "./pages/SpendingPage";
import { TransactionsPage } from "./pages/TransactionsPage";

export function App() {
  const workspace = useWorkspace();
  const ownerCategories = workspace.workspace.categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  const gates = {
    accountCount: workspace.workspace.accounts.length,
    categoryCount: ownerCategories.length,
  };
  const { state: setup, dispatch: setupDispatch } = useSetup(gates);
  const configured = gatesMet(gates);
  const workspaceReady = !workspace.loading;
  const onboarded = setup.onboarded || (workspaceReady && configured);
  const { route, go } = useRoute(onboarded);
  const { theme, toggleTheme } = useTheme();
  const [categoryDraft, setCategoryDraft] = useState<Record<string, string>>(
    {},
  );
  const [listCategory, setListCategory] = useState("");
  const [listAccount, setListAccount] = useState("");
  const [reviewSelection, setReviewSelection] = useState("");
  const [toast, setToast] = useState("");
  const today = useMemo(() => new Date(), []);

  useEffect(() => {
    if (toast === "") {
      return;
    }
    const timer = window.setTimeout(() => {
      setToast("");
    }, 1600);
    return () => {
      window.clearTimeout(timer);
    };
  }, [toast]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && route.drawerId !== null) {
        go({ ...route, drawerId: null });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [go, route]);

  const blockingCount = workspace.workspace.reviews.filter(
    (review) => review.severity === "blocking",
  ).length;
  const drawerTransaction =
    workspace.workspace.transactions.items.find(
      (item) => item.id === route.drawerId,
    ) ?? null;

  function navigate(page: Route["page"]) {
    go({
      page,
      ...emptyRoute,
    });
  }

  function openTransactions(
    confirmation: ConfirmationFilter,
    category = "",
    accountId = "",
  ) {
    setListCategory(category);
    setListAccount(accountId);
    go({
      page: "transactions",
      reviewFilter: "",
      confirmation,
      drawerId: null,
      importId: null,
      accountId: null,
    });
  }

  function setReviewFilter(filter: ReviewFilter) {
    go({
      page: "review",
      reviewFilter: filter,
      confirmation: "",
      drawerId: null,
      importId: null,
      accountId: null,
    });
  }

  function openDrawer(id: string) {
    go({
      page: "transactions",
      reviewFilter: "",
      confirmation: route.page === "transactions" ? route.confirmation : "",
      drawerId: id,
      importId: null,
      accountId: null,
    });
  }

  function openImport(id: string | null = null) {
    go({
      page: "imports",
      reviewFilter: "",
      confirmation: "",
      drawerId: null,
      importId: id,
      accountId: route.accountId,
    });
  }

  function openAccountImports(accountId: string) {
    go({
      page: "imports",
      ...emptyRoute,
      accountId,
    });
  }

  async function assignCategory(transaction: Transaction): Promise<boolean> {
    const listed = workspace.workspace.transactions.items.find(
      (item) => item.id === transaction.id,
    );
    const target = listed ?? transaction;
    const categoryId = categoryDraft[target.id] ?? "";
    if (categoryId === "") {
      return false;
    }
    const ok = await workspace.saveCategory(target, categoryId);
    if (ok) {
      setCategoryDraft((current) => ({ ...current, [target.id]: "" }));
      setToast(`Category assigned to ${target.counterparty}`);
    }
    return ok;
  }

  async function assignMany(ids: string[], categoryId: string): Promise<void> {
    const items = workspace.workspace.transactions.items;
    for (const id of ids) {
      const target = items.find((item) => item.id === id);
      if (target === undefined) {
        continue;
      }
      await workspace.saveCategory(target, categoryId);
    }
  }

  const showOnboarding = workspaceReady && !setup.onboarded && !configured;
  if (showOnboarding) {
    return (
      <OnboardingPage
        state={setup}
        dispatch={setupDispatch}
        gates={gates}
        identity={workspace.workspace.identity}
        accounts={workspace.workspace.accounts}
        adapters={workspace.workspace.adapters}
        categories={workspace.workspace.categories}
        tokens={workspace.workspace.tokens}
        issuedToken={workspace.issuedToken}
        saving={workspace.saving}
        transactionCount={workspace.workspace.transactions.items.length}
        reviewCount={workspace.workspace.reviews.length}
        blockingCount={blockingCount}
        onCreateAccount={workspace.addAccount}
        onAddAlias={workspace.addWalletAlias}
        onCreateCategory={workspace.addCategory}
        onIssueToken={workspace.addToken}
        onRotateToken={workspace.replaceToken}
        onRevokeToken={workspace.removeToken}
        onDismissIssuedToken={workspace.dismissIssuedToken}
        onReturn={() => {
          go({
            page: "overview",
            ...emptyRoute,
          });
        }}
      />
    );
  }

  if (!workspaceReady && !setup.onboarded) {
    return (
      <div className="app is-onboarding">
        <div className="onboard">
          <article className="card onboard-card">
            <p className="eyebrow">Billzebub</p>
            <h1>Loading workspace…</h1>
          </article>
        </div>
      </div>
    );
  }

  return (
    <>
      <AppShell
        route={route}
        periodLabel={monthYearLabel(isoDate(today))}
        reviewCount={workspace.workspace.reviews.length}
        reviewBlocking={blockingCount > 0}
        accounts={workspace.workspace.accounts}
        selectedAccountId={listAccount}
        theme={theme}
        error={workspace.error}
        onNavigate={navigate}
        onSelectAccount={(accountId) => {
          if (listAccount === accountId && route.page === "transactions") {
            setListAccount("");
            return;
          }
          openTransactions(
            route.page === "transactions" ? route.confirmation : "",
            listCategory,
            accountId,
          );
        }}
        onToggleTheme={toggleTheme}
      >
        {route.page === "overview" ? (
          <OverviewPage
            transactions={workspace.workspace.transactions.items}
            reviewCount={workspace.workspace.reviews.length}
            blockingCount={blockingCount}
            today={today}
            onOpenTransaction={openDrawer}
            onFilterConfirmed={() => {
              openTransactions("confirmed");
            }}
            onFilterProvisional={() => {
              openTransactions("provisional");
            }}
            onOpenReview={() => {
              navigate("review");
            }}
            onOpenTransactions={() => {
              openTransactions("");
            }}
            onFilterCategory={(name) => {
              openTransactions("confirmed", name);
            }}
          />
        ) : null}
        {route.page === "spending" ? (
          <SpendingPage
            transactions={workspace.workspace.transactions.items}
            today={today}
            onOpenTransactions={() => {
              openTransactions("");
            }}
          />
        ) : null}
        {route.page === "review" ? (
          <ReviewPage
            reviews={workspace.workspace.reviews}
            transactions={workspace.workspace.transactions.items}
            imports={workspace.workspace.imports}
            categories={ownerCategories}
            filter={route.reviewFilter}
            selectedId={reviewSelection}
            drafts={categoryDraft}
            saving={workspace.saving}
            today={today}
            onFilter={setReviewFilter}
            onSelect={setReviewSelection}
            onDraft={(transactionId, categoryId) => {
              setCategoryDraft((current) => ({
                ...current,
                [transactionId]: categoryId,
              }));
            }}
            onAssign={assignCategory}
            onDecide={(review, choice) =>
              workspace.resolveReview(review, choice).then((ok) => {
                if (ok) {
                  setToast(decisionToast(choice));
                }
                return ok;
              })
            }
            onOpenTransaction={openDrawer}
            onOpenImport={openImport}
            onOpenSettings={() => {
              navigate("settings");
            }}
          />
        ) : null}
        {route.page === "imports" ? (
          <ImportsPage
            imports={workspace.workspace.imports}
            coverage={workspace.workspace.coverage}
            selectedId={route.importId}
            accountId={route.accountId}
            today={today}
            includeDismissed={workspace.includeDismissed}
            saving={workspace.saving}
            onSelect={openImport}
            onSelectAccount={openAccountImports}
            onClearAccount={() => {
              go({
                page: "imports",
                ...emptyRoute,
                importId: route.importId,
              });
            }}
            onOpenReview={(reviewId) => {
              setReviewSelection(reviewId);
              go({
                page: "review",
                ...emptyRoute,
              });
            }}
            onShowDismissed={(show) => {
              void workspace.showDismissedImports(show);
            }}
            onDismiss={(extractionId) => {
              void workspace.dismissFailedExtraction(extractionId);
            }}
            onDismissFailed={() => {
              void workspace.dismissAllFailedExtractions();
            }}
          />
        ) : null}
        {route.page === "transactions" ? (
          <TransactionsPage
            transactions={workspace.workspace.transactions.items}
            categories={ownerCategories}
            accounts={workspace.workspace.accounts.map((account) => ({
              id: account.id,
              name: account.display_name,
            }))}
            confirmation={route.confirmation}
            category={listCategory}
            accountId={listAccount}
            selectedId={route.drawerId}
            today={today}
            loadingMore={workspace.loadingMore}
            hasMore={workspace.workspace.transactions.next_cursor !== null}
            saving={workspace.saving}
            onConfirmation={(value) => {
              go({
                page: "transactions",
                reviewFilter: "",
                confirmation: value,
                drawerId: null,
                importId: null,
                accountId: null,
              });
            }}
            onCategory={setListCategory}
            onAccount={setListAccount}
            onOpen={openDrawer}
            onLoadMore={() => {
              void workspace.loadMoreTransactions();
            }}
            onCategorizeMany={assignMany}
            detail={
              drawerTransaction === null ? null : (
                <TransactionDrawer
                  transaction={drawerTransaction}
                  categories={ownerCategories}
                  draft={categoryDraft[drawerTransaction.id] ?? ""}
                  saving={workspace.saving === drawerTransaction.id}
                  onDraft={(categoryId) => {
                    setCategoryDraft((current) => ({
                      ...current,
                      [drawerTransaction.id]: categoryId,
                    }));
                  }}
                  onSave={(transaction) => {
                    void assignCategory(transaction);
                  }}
                  onClose={() => {
                    go({ ...route, drawerId: null });
                  }}
                />
              )
            }
          />
        ) : null}
        {route.page === "settings" ? (
          <SettingsPage
            identity={workspace.workspace.identity}
            accounts={workspace.workspace.accounts}
            adapters={workspace.workspace.adapters}
            categories={workspace.workspace.categories}
            tokens={workspace.workspace.tokens}
            issuedToken={workspace.issuedToken}
            coverage={workspace.workspace.coverage}
            saving={workspace.saving}
            onCreateAccount={workspace.addAccount}
            onAddAlias={workspace.addWalletAlias}
            onCreateCategory={workspace.addCategory}
            onIssueToken={workspace.addToken}
            onRotateToken={workspace.replaceToken}
            onRevokeToken={workspace.removeToken}
            onDismissIssuedToken={workspace.dismissIssuedToken}
            onOpenAccountImports={openAccountImports}
            theme={theme}
            onToggleTheme={toggleTheme}
          />
        ) : null}
      </AppShell>
      {toast !== "" ? (
        <div className="toast" role="status">
          {toast}
        </div>
      ) : null}
    </>
  );
}

function decisionToast(choice: string): string {
  return choice
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
