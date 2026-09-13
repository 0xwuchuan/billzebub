import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  categorizeTransaction,
  decideReview,
  getCategories,
  getReviews,
  getTransactions,
  type Category,
  type Review,
  type Transaction,
  type TransactionPage,
} from "./api";

type WorkspaceState = {
  transactions: TransactionPage;
  reviews: Review[];
  categories: Category[];
};

const emptyWorkspace: WorkspaceState = {
  transactions: { items: [], next_cursor: null },
  reviews: [],
  categories: [],
};

export function App() {
  const [workspace, setWorkspace] = useState<WorkspaceState>(emptyWorkspace);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [categoryChoice, setCategoryChoice] = useState<Record<string, string>>(
    {},
  );

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [transactions, reviews, categories] = await Promise.all([
        getTransactions(),
        getReviews(),
        getCategories(),
      ]);
      setWorkspace({
        transactions,
        reviews: reviews.items,
        categories: categories.items,
      });
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void fetchWorkspace()
      .then((nextWorkspace) => {
        if (active) {
          setWorkspace(nextWorkspace);
        }
      })
      .catch((requestError: unknown) => {
        if (active) {
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

  async function saveCategory(transaction: Transaction): Promise<void> {
    const categoryId = categoryChoice[transaction.id];
    if (categoryId === undefined || categoryId === "") {
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
      setCategoryChoice((current) => ({ ...current, [transaction.id]: "" }));
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

  const availableCategories = workspace.categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  const blockingReviews = workspace.reviews.filter(
    (review) => review.severity === "blocking",
  );
  const attentionReviews = workspace.reviews.filter(
    (review) => review.severity === "attention",
  );

  return (
    <main className="workspace-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Local financial history</p>
          <h1>Billzebub</h1>
        </div>
        <button
          className="quiet-button"
          onClick={() => void loadWorkspace()}
          type="button"
        >
          Refresh
        </button>
      </header>

      <section aria-label="Workspace summary" className="summary-grid">
        <SummaryCard
          label="Transactions"
          value={String(workspace.transactions.items.length)}
        />
        <SummaryCard
          label="Blocking reviews"
          value={String(blockingReviews.length)}
          tone="blocking"
        />
        <SummaryCard
          label="Attention reviews"
          value={String(attentionReviews.length)}
          tone="attention"
        />
      </section>

      {error !== null ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}

      <section aria-labelledby="transactions-heading" className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Current financial history</p>
            <h2 id="transactions-heading">Transactions</h2>
          </div>
          <span className="status-copy">
            Confirmed statement-backed movements
          </span>
        </div>

        {loading ? (
          <p className="empty-state">Loading local workspace…</p>
        ) : null}
        {!loading && workspace.transactions.items.length === 0 ? (
          <p className="empty-state">
            No trusted Transactions yet. Process an accepted statement to begin.
          </p>
        ) : null}
        <div className="transaction-list">
          {workspace.transactions.items.map((transaction) => {
            const needsCategorization = transaction.reviews.some(
              (review) => review.condition_code === "categorization_needed",
            );
            const selectedCategory = categoryChoice[transaction.id] ?? "";
            return (
              <article className="transaction-row" key={transaction.id}>
                <div className="transaction-date">
                  {transaction.effective_date}
                </div>
                <div className="transaction-main">
                  <h3>{transaction.counterparty}</h3>
                  <p>
                    {transaction.financial_account.name} ·{" "}
                    {kindLabel(transaction.kind)} · {categoryLabel(transaction)}
                  </p>
                </div>
                <strong className="amount">
                  {formatMoney(transaction.posted_amount)}
                </strong>
                {needsCategorization ? (
                  <div className="categorize-control">
                    <label
                      className="sr-only"
                      htmlFor={`category-${transaction.id}`}
                    >
                      Category for {transaction.counterparty}
                    </label>
                    <select
                      id={`category-${transaction.id}`}
                      onChange={(event) =>
                        setCategoryChoice((current) => ({
                          ...current,
                          [transaction.id]: event.target.value,
                        }))
                      }
                      value={selectedCategory}
                    >
                      <option value="">Choose category</option>
                      {availableCategories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                    <button
                      className="primary-button"
                      disabled={
                        selectedCategory === "" || saving === transaction.id
                      }
                      onClick={() => void saveCategory(transaction)}
                      type="button"
                    >
                      {saving === transaction.id ? "Saving…" : "Categorize"}
                    </button>
                  </div>
                ) : (
                  <span className="confirmed-badge">Categorized</span>
                )}
              </article>
            );
          })}
        </div>
        {workspace.transactions.next_cursor !== null ? (
          <div className="load-more">
            <button
              className="quiet-button"
              disabled={loadingMore}
              onClick={() => void loadMoreTransactions()}
              type="button"
            >
              {loadingMore ? "Loading…" : "Load older Transactions"}
            </button>
          </div>
        ) : null}
      </section>

      <section aria-labelledby="reviews-heading" className="panel review-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Durable workflow</p>
            <h2 id="reviews-heading">Reviews</h2>
          </div>
          <span className="status-copy">
            Only permitted decisions are available
          </span>
        </div>
        <ReviewQueue
          label="Blocking"
          reviews={blockingReviews}
          saving={saving}
          onDecide={resolveReview}
        />
        <ReviewQueue
          label="Attention"
          reviews={attentionReviews}
          saving={saving}
          onDecide={resolveReview}
        />
      </section>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "attention" | "blocking";
}) {
  return (
    <article
      className={`summary-card ${tone === undefined ? "" : `summary-${tone}`}`}
    >
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}

function ReviewQueue({
  label,
  reviews,
  saving,
  onDecide,
}: {
  label: string;
  reviews: Review[];
  saving: string | null;
  onDecide: (review: Review, choice: string) => Promise<void>;
}) {
  return (
    <div className="review-queue">
      <h3>{label}</h3>
      {reviews.length === 0 ? (
        <p className="empty-state">No {label.toLowerCase()} Reviews.</p>
      ) : null}
      {reviews.map((review) => {
        const categorization =
          review.condition_code === "categorization_needed";
        return (
          <article className="review-row" key={review.id}>
            <div>
              <p className={`review-severity review-${review.severity}`}>
                {review.severity}
              </p>
              <h4>{reviewTitle(review.condition_code)}</h4>
              <p>
                {categorization
                  ? "Choose a Category from the Transaction row."
                  : "Review the permitted decision."}
              </p>
            </div>
            <div className="review-actions">
              {categorization ? (
                <span className="status-copy">Transaction action required</span>
              ) : null}
              {!categorization
                ? review.allowed_decisions.map((choice) => (
                    <button
                      className="quiet-button"
                      disabled={saving === review.id}
                      key={choice}
                      onClick={() => void onDecide(review, choice)}
                      type="button"
                    >
                      {saving === review.id ? "Saving…" : decisionLabel(choice)}
                    </button>
                  ))
                : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function formatMoney(money: { amount: string; currency: string }): string {
  const negative = money.amount.startsWith("-");
  const absolute = negative ? money.amount.slice(1) : money.amount;
  const [whole = "0", fraction] = absolute.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${money.currency} ${grouped}${fraction === undefined ? "" : `.${fraction}`}`;
}

function categoryLabel(transaction: Transaction): string {
  return (
    transaction.category_splits.map((split) => split.name).join(", ") ||
    "Uncategorized"
  );
}

function kindLabel(kind: string): string {
  return kind.replaceAll("_", " ");
}

function reviewTitle(condition: string): string {
  if (condition === "categorization_needed") {
    return "Category needed";
  }
  return condition
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function decisionLabel(choice: string): string {
  return choice
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

async function fetchWorkspace(): Promise<WorkspaceState> {
  const [transactions, reviews, categories] = await Promise.all([
    getTransactions(),
    getReviews(),
    getCategories(),
  ]);
  return { transactions, reviews: reviews.items, categories: categories.items };
}

function messageFor(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The local workspace is unavailable. Check the API and refresh.";
}
