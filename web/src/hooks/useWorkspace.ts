import { useCallback, useEffect, useState } from "react";

import {
  categorizeTransaction,
  createCategory,
  createFinancialAccount,
  createWalletAlias,
  decideReview,
  dismissFailedImports,
  dismissImport,
  getCategories,
  getFinancialAccounts,
  getImports,
  getReviews,
  getStatementAdapters,
  getStatementCoverage,
  getTokens,
  getTransactions,
  getWhoami,
  issueToken,
  revokeToken,
  rotateToken,
  updateCategory,
  type Category,
  type CategoryPatch,
  type CreateFinancialAccountInput,
  type FinancialAccount,
  type IssuedToken,
  type ImportRecord,
  type IntegrationToken,
  type OwnerIdentity,
  type Review,
  type StatementAdapter,
  type StatementCoverageReport,
  type Transaction,
  type TransactionPage,
} from "../api";
import { useFixtureMode, type FixtureMode } from "../dev/fixtureMode";
import { messageFor } from "../lib/labels";

export type WorkspaceSnapshot = {
  identity: OwnerIdentity | null;
  transactions: TransactionPage;
  reviews: Review[];
  imports: ImportRecord[];
  coverage: StatementCoverageReport | null;
  categories: Category[];
  accounts: FinancialAccount[];
  adapters: StatementAdapter[];
  tokens: IntegrationToken[];
};

const emptyWorkspace: WorkspaceSnapshot = {
  identity: null,
  transactions: { items: [], next_cursor: null },
  reviews: [],
  imports: [],
  coverage: null,
  categories: [],
  accounts: [],
  adapters: [],
  tokens: [],
};

export function useWorkspace() {
  const [workspace, setWorkspace] = useState<WorkspaceSnapshot>(emptyWorkspace);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [issuedToken, setIssuedToken] = useState<IssuedToken | null>(null);
  const [includeDismissed, setIncludeDismissed] = useState(false);
  const fixtureMode = useFixtureMode();

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWorkspace(await loadSnapshot(includeDismissed, fixtureMode));
    } catch (requestError) {
      setWorkspace(emptyWorkspace);
      setError(messageFor(requestError));
    } finally {
      setLoading(false);
    }
  }, [fixtureMode, includeDismissed]);

  useEffect(() => {
    if (import.meta.env.DEV && fixtureMode !== null) {
      return;
    }
    let active = true;
    void fetchWorkspace()
      .then((next) => {
        if (active) {
          setWorkspace(next);
        }
      })
      .catch((requestError: unknown) => {
        if (active) {
          setWorkspace(emptyWorkspace);
          setError(messageFor(requestError));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [fixtureMode]);

  useEffect(() => {
    if (!import.meta.env.DEV || fixtureMode === null) {
      return;
    }
    let active = true;
    void loadSnapshot(includeDismissed, fixtureMode)
      .then((next) => {
        if (active) {
          setWorkspace(next);
          setError(null);
        }
      })
      .catch((requestError: unknown) => {
        if (active) {
          setWorkspace(emptyWorkspace);
          setError(messageFor(requestError));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [fixtureMode, includeDismissed]);

  async function loadMoreTransactions(): Promise<void> {
    const cursor = workspace.transactions.next_cursor;
    if (cursor === null || (import.meta.env.DEV && fixtureMode !== null)) {
      return;
    }
    setLoadingMore(true);
    setError(null);
    try {
      const page = await getTransactions(cursor);
      setWorkspace((current) => ({
        ...current,
        transactions: {
          items: [...current.transactions.items, ...page.items],
          next_cursor: page.next_cursor,
        },
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setLoadingMore(false);
    }
  }

  async function saveCategory(
    transaction: Transaction,
    categoryId: string,
  ): Promise<boolean> {
    if (categoryId === "") {
      return false;
    }
    if (import.meta.env.DEV && fixtureMode !== null) {
      const category = workspace.categories.find(
        (item) => item.id === categoryId,
      );
      if (category === undefined) {
        return false;
      }
      setWorkspace((current) => ({
        ...current,
        transactions: {
          ...current.transactions,
          items: current.transactions.items.map((item) =>
            item.id === transaction.id
              ? {
                  ...item,
                  category_splits: [
                    {
                      id: category.id,
                      name: category.name,
                      amount: item.posted_amount,
                    },
                  ],
                  reviews: item.reviews.filter(
                    (review) =>
                      review.condition_code !== "categorization_needed",
                  ),
                }
              : item,
          ),
        },
        reviews: current.reviews.filter(
          (review) =>
            !(
              review.subject_type === "transaction" &&
              review.subject_id === transaction.id &&
              review.condition_code === "categorization_needed"
            ),
        ),
      }));
      return true;
    }
    setSaving(transaction.id);
    setError(null);
    try {
      const updated = await categorizeTransaction(transaction, categoryId);
      setWorkspace((current) => ({
        ...current,
        transactions: {
          ...current.transactions,
          items: current.transactions.items.map((item) =>
            item.id === updated.id ? updated : item,
          ),
        },
        reviews: current.reviews.filter(
          (review) =>
            !(
              review.subject_type === "transaction" &&
              review.subject_id === updated.id &&
              review.condition_code === "categorization_needed"
            ),
        ),
      }));
      return true;
    } catch (requestError) {
      setError(messageFor(requestError));
      return false;
    } finally {
      setSaving(null);
    }
  }

  async function resolveReview(
    review: Review,
    choice: string,
  ): Promise<boolean> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setWorkspace((current) => ({
        ...current,
        reviews: current.reviews.filter((item) => item.id !== review.id),
      }));
      return true;
    }
    setSaving(review.id);
    setError(null);
    try {
      await decideReview(review, choice);
      setWorkspace((current) => ({
        ...current,
        reviews: current.reviews.filter((item) => item.id !== review.id),
      }));
      return true;
    } catch (requestError) {
      setError(messageFor(requestError));
      return false;
    } finally {
      setSaving(null);
    }
  }

  async function addAccount(input: CreateFinancialAccountInput): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setError("Example data stays in the browser. Nothing was written.");
      return;
    }
    setSaving("account");
    setError(null);
    try {
      const account = await createFinancialAccount(input);
      setWorkspace((current) => ({
        ...current,
        accounts: [...current.accounts, account],
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function addWalletAlias(
    accountId: string,
    cardLabel: string,
  ): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setError("Example data stays in the browser. Nothing was written.");
      return;
    }
    setSaving("alias");
    setError(null);
    try {
      const alias = await createWalletAlias(accountId, cardLabel);
      setWorkspace((current) => ({
        ...current,
        accounts: current.accounts.map((account) =>
          account.id === accountId
            ? { ...account, aliases: [...account.aliases, alias] }
            : account,
        ),
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function addCategory(name: string, parentId?: string): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      const category: Category = {
        id: `example-local-${name.toLowerCase()}`,
        name,
        parent_id: parentId ?? null,
        active: true,
        version: 1,
      };
      setWorkspace((current) => ({
        ...current,
        categories: [...current.categories, category],
      }));
      return;
    }
    setSaving("category");
    setError(null);
    try {
      const category = await createCategory(name, parentId);
      setWorkspace((current) => ({
        ...current,
        categories: [...current.categories, category],
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function reviseCategory(
    category: Category,
    patch: CategoryPatch,
  ): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setWorkspace((current) => ({
        ...current,
        categories: current.categories.map((item) =>
          item.id === category.id
            ? { ...item, ...patch, version: (item.version ?? 1) + 1 }
            : item,
        ),
      }));
      return;
    }
    setSaving("category");
    setError(null);
    try {
      const updated = await updateCategory(category, patch);
      setWorkspace((current) => ({
        ...current,
        categories: current.categories.map((item) =>
          item.id === updated.id ? updated : item,
        ),
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function addToken(): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setError("Example data stays in the browser. Nothing was written.");
      return;
    }
    setSaving("token");
    setError(null);
    try {
      const issued = await issueToken({
        name: "Apple Shortcut",
        kind: "integration",
        scopes: ["shortcut:claims:create"],
      });
      setIssuedToken(issued);
      setWorkspace((current) => ({
        ...current,
        tokens: [
          ...current.tokens,
          {
            id: issued.id,
            name: issued.name,
            prefix: issued.prefix,
            scopes: issued.scopes,
            created_at: issued.created_at,
            last_used_at: issued.last_used_at,
          },
        ],
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function replaceToken(tokenId: string): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setError("Example data stays in the browser. Nothing was written.");
      return;
    }
    setSaving(tokenId);
    setError(null);
    try {
      const issued = await rotateToken(tokenId);
      setIssuedToken(issued);
      setWorkspace((current) => ({
        ...current,
        tokens: current.tokens.map((token) =>
          token.id === tokenId
            ? {
                id: issued.id,
                name: issued.name,
                prefix: issued.prefix,
                scopes: issued.scopes,
                created_at: issued.created_at,
                last_used_at: issued.last_used_at,
              }
            : token,
        ),
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function removeToken(tokenId: string): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      setError("Example data stays in the browser. Nothing was written.");
      return;
    }
    setSaving(tokenId);
    setError(null);
    try {
      await revokeToken(tokenId);
      setIssuedToken((current) => (current?.id === tokenId ? null : current));
      setWorkspace((current) => ({
        ...current,
        tokens: current.tokens.filter((token) => token.id !== tokenId),
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function refreshImports(showDismissed: boolean): Promise<void> {
    const page = await getImports(showDismissed);
    setWorkspace((current) => ({ ...current, imports: page.items }));
  }

  async function showDismissedImports(show: boolean): Promise<void> {
    setIncludeDismissed(show);
    if (import.meta.env.DEV && fixtureMode !== null) {
      return;
    }
    setError(null);
    try {
      await refreshImports(show);
    } catch (requestError) {
      setError(messageFor(requestError));
    }
  }

  async function dismissFailedExtraction(extractionId: string): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      const dismissedAt = new Date().toISOString();
      setWorkspace((current) => ({
        ...current,
        imports: current.imports.flatMap((item) => {
          if (item.id !== extractionId) {
            return [item];
          }
          if (!includeDismissed) {
            return [];
          }
          return [{ ...item, dismissed_at: dismissedAt }];
        }),
      }));
      return;
    }
    setSaving(extractionId);
    setError(null);
    try {
      await dismissImport(extractionId);
      await refreshImports(includeDismissed);
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function dismissAllFailedExtractions(): Promise<void> {
    if (import.meta.env.DEV && fixtureMode !== null) {
      const dismissedAt = new Date().toISOString();
      setWorkspace((current) => ({
        ...current,
        imports: includeDismissed
          ? current.imports.map((item) =>
              item.status === "failed" && item.dismissed_at === null
                ? { ...item, dismissed_at: dismissedAt }
                : item,
            )
          : current.imports.filter(
              (item) => item.status !== "failed" || item.dismissed_at !== null,
            ),
      }));
      return;
    }
    setSaving("imports-dismiss-failed");
    setError(null);
    try {
      await dismissFailedImports();
      await refreshImports(includeDismissed);
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  return {
    workspace,
    loading,
    error,
    saving,
    loadingMore,
    issuedToken,
    includeDismissed,
    loadWorkspace,
    loadMoreTransactions,
    saveCategory,
    resolveReview,
    addAccount,
    addWalletAlias,
    addCategory,
    reviseCategory,
    addToken,
    replaceToken,
    removeToken,
    showDismissedImports,
    dismissFailedExtraction,
    dismissAllFailedExtractions,
    dismissIssuedToken: () => {
      setIssuedToken(null);
    },
  };
}

async function loadSnapshot(
  includeDismissed: boolean,
  mode: FixtureMode | null,
): Promise<WorkspaceSnapshot> {
  if (import.meta.env.DEV && mode !== null) {
    const { workspaceFor } = await import("../dev/worstCaseFixture");
    return workspaceFor(mode, { includeDismissed });
  }
  return fetchWorkspace(includeDismissed);
}

async function fetchWorkspace(
  includeDismissed = false,
): Promise<WorkspaceSnapshot> {
  const [
    identity,
    transactions,
    reviews,
    imports,
    coverage,
    categories,
    accounts,
    adapters,
    tokens,
  ] = await Promise.all([
    getWhoami(),
    getTransactions(),
    getReviews(),
    getImports(includeDismissed),
    getStatementCoverage(),
    getCategories(),
    getFinancialAccounts(),
    getStatementAdapters(),
    getTokens(),
  ]);
  return {
    identity,
    transactions,
    reviews: reviews.items,
    imports: imports.items,
    coverage,
    categories: categories.items,
    accounts: accounts.items,
    adapters: adapters.items,
    tokens: tokens.items,
  };
}
