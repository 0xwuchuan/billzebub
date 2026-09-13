import { useCallback, useEffect, useState } from "react";

import {
  categorizeTransaction,
  decideReview,
  getCategories,
  getReviews,
  getTransactions,
  type Category,
  type Review,
  type Transaction,
  type TransactionPage,
} from "../api";
import { messageFor } from "../lib/labels";

export type WorkspaceSnapshot = {
  transactions: TransactionPage;
  reviews: Review[];
  categories: Category[];
};

const emptyWorkspace: WorkspaceSnapshot = {
  transactions: { items: [], next_cursor: null },
  reviews: [],
  categories: [],
};

export function useWorkspace() {
  const [workspace, setWorkspace] = useState<WorkspaceSnapshot>(emptyWorkspace);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

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

  return {
    workspace,
    loading,
    error,
    saving,
    loadingMore,
    loadWorkspace,
    loadMoreTransactions,
    saveCategory,
    resolveReview,
  };
}

async function fetchWorkspace(): Promise<WorkspaceSnapshot> {
  const [transactions, reviews, categories] = await Promise.all([
    getTransactions(),
    getReviews(),
    getCategories(),
  ]);
  return {
    transactions,
    reviews: reviews.items,
    categories: categories.items,
  };
}
