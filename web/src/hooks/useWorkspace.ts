import { useCallback, useEffect, useState } from "react";

import {
  categorizeTransaction,
  createCategory,
  createFinancialAccount,
  createWalletAlias,
  decideReview,
  getCategories,
  getFinancialAccounts,
  getImports,
  getReviews,
  getStatementAdapters,
  getTokens,
  getTransactions,
  getWhoami,
  issueToken,
  revokeToken,
  rotateToken,
  type Category,
  type CreateFinancialAccountInput,
  type FinancialAccount,
  type IssuedToken,
  type ImportRecord,
  type IntegrationToken,
  type OwnerIdentity,
  type Review,
  type StatementAdapter,
  type Transaction,
  type TransactionPage,
} from "../api";
import { messageFor } from "../lib/labels";

export type WorkspaceSnapshot = {
  identity: OwnerIdentity | null;
  transactions: TransactionPage;
  reviews: Review[];
  imports: ImportRecord[];
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

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWorkspace(await fetchWorkspace());
    } catch (requestError) {
      setWorkspace(emptyWorkspace);
      setError(messageFor(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
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
  }, []);

  async function loadMoreTransactions(): Promise<void> {
    const cursor = workspace.transactions.next_cursor;
    if (cursor === null) {
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
  ): Promise<void> {
    if (categoryId === "") {
      return;
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
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function resolveReview(review: Review, choice: string): Promise<void> {
    setSaving(review.id);
    setError(null);
    try {
      await decideReview(review, choice);
      setWorkspace((current) => ({
        ...current,
        reviews: current.reviews.filter((item) => item.id !== review.id),
      }));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setSaving(null);
    }
  }

  async function addAccount(input: CreateFinancialAccountInput): Promise<void> {
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

  async function addToken(): Promise<void> {
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

  return {
    workspace,
    loading,
    error,
    saving,
    loadingMore,
    issuedToken,
    loadWorkspace,
    loadMoreTransactions,
    saveCategory,
    resolveReview,
    addAccount,
    addWalletAlias,
    addCategory,
    addToken,
    replaceToken,
    removeToken,
    dismissIssuedToken: () => {
      setIssuedToken(null);
    },
  };
}

async function fetchWorkspace(): Promise<WorkspaceSnapshot> {
  const [
    identity,
    transactions,
    reviews,
    imports,
    categories,
    accounts,
    adapters,
    tokens,
  ] = await Promise.all([
    getWhoami(),
    getTransactions(),
    getReviews(),
    getImports(),
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
    categories: categories.items,
    accounts: accounts.items,
    adapters: adapters.items,
    tokens: tokens.items,
  };
}
