import type { Category, Review, Transaction } from "../api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import {
  contextString,
  contextStrings,
  filterReviews,
  transactionForReview,
} from "../lib/workspace";
import { decisionLabel, openedLabel, reviewTitle } from "../lib/labels";
import { formatUnsigned } from "../lib/money";
import type { ReviewFilter } from "../lib/route";

export function ReviewPage({
  reviews,
  transactions,
  categories,
  filter,
  selectedId,
  drafts,
  saving,
  today,
  onFilter,
  onSelect,
  onDraft,
  onAssign,
  onDecide,
  onOpenTransaction,
  onOpenSetup,
}: {
  reviews: Review[];
  transactions: Transaction[];
  categories: Category[];
  filter: ReviewFilter;
  selectedId: string;
  drafts: Record<string, string>;
  saving: string | null;
  today: Date;
  onFilter: (filter: ReviewFilter) => void;
  onSelect: (id: string) => void;
  onDraft: (transactionId: string, categoryId: string) => void;
  onAssign: (transaction: Transaction) => void;
  onDecide: (review: Review, choice: string) => void;
  onOpenTransaction: (id: string) => void;
  onOpenSetup: () => void;
}) {
  const fresh = useEntrance("review");
  const items = filterReviews(reviews, filter);
  const selected =
    items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  return (
    <>
      <div className={`filters${fresh ? " stage-enter" : ""}`}>
        {(
          [
            ["", "All"],
            ["blocking", "Blocking"],
            ["attention", "Attention"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={label}
            className="chip"
            type="button"
            aria-pressed={filter === value}
            onClick={() => {
              onFilter(value);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="desk">
        <section className="card queue-pane" aria-label="Pending Review queue">
          <div className="panel-head">
            <h2>Queue</h2>
            <span className="muted" style={{ fontSize: "var(--bz-text-sm)" }}>
              {items.length} open · blocking first
            </span>
          </div>
          {items.length === 0 ? (
            <p className="empty">
              No Pending Review in this filter. Confirmed history is up to date.
            </p>
          ) : (
            <div className="queue-list">
              {items.map((item) => (
                <QueueItem
                  key={item.id}
                  review={item}
                  transaction={transactionForReview(item, transactions)}
                  current={selected !== null && selected.id === item.id}
                  today={today}
                  onSelect={onSelect}
                />
              ))}
            </div>
          )}
        </section>
        <section className="card evidence-pane" aria-live="polite">
          {selected === null ? (
            <p className="empty">
              Nothing to decide. Pick another filter or come back after the next
              Extraction.
            </p>
          ) : (
            <Evidence
              review={selected}
              transaction={transactionForReview(selected, transactions)}
              categories={categories}
              draft={
                selected.subject_type === "transaction"
                  ? (drafts[selected.subject_id] ?? "")
                  : ""
              }
              saving={saving}
              today={today}
              onDraft={onDraft}
              onAssign={onAssign}
              onDecide={onDecide}
              onOpenTransaction={onOpenTransaction}
              onOpenSetup={onOpenSetup}
            />
          )}
        </section>
      </div>
    </>
  );
}

function QueueItem({
  review,
  transaction,
  current,
  today,
  onSelect,
}: {
  review: Review;
  transaction: Transaction | undefined;
  current: boolean;
  today: Date;
  onSelect: (id: string) => void;
}) {
  const blocking = review.severity === "blocking";
  return (
    <button
      className={`queue-item${blocking ? " is-blocking" : ""}`}
      type="button"
      aria-current={current}
      onClick={() => {
        onSelect(review.id);
      }}
    >
      <span>
        <span className="queue-title">
          {reviewTitle(review.condition_code)}
        </span>
        <span className="queue-reason">
          {queueSubject(review, transaction)}
        </span>
      </span>
      <span className="queue-right">
        <span className="amount">
          {transaction === undefined
            ? "Source Artifact"
            : formatUnsigned(transaction.posted_amount)}
        </span>
        <span className="queue-age">
          {openedLabel(review.created_at, today)}
        </span>
      </span>
    </button>
  );
}

function Evidence({
  review,
  transaction,
  categories,
  draft,
  saving,
  today,
  onDraft,
  onAssign,
  onDecide,
  onOpenTransaction,
  onOpenSetup,
}: {
  review: Review;
  transaction: Transaction | undefined;
  categories: Category[];
  draft: string;
  saving: string | null;
  today: Date;
  onDraft: (transactionId: string, categoryId: string) => void;
  onAssign: (transaction: Transaction) => void;
  onDecide: (review: Review, choice: string) => void;
  onOpenTransaction: (id: string) => void;
  onOpenSetup: () => void;
}) {
  const fresh = useEntrance(`review:${review.id}`);
  const blocking = review.severity === "blocking";
  const claims = contextStrings(review.context, "claims");
  const raw =
    contextString(review.context, "raw") ??
    transaction?.counterparty ??
    review.subject_id;
  const account =
    contextString(review.context, "account") ??
    transaction?.financial_account.name ??
    review.subject_type;
  const categorization = review.condition_code === "categorization_needed";
  const needsSetup =
    review.condition_code === "apple_wallet_unmapped_card" ||
    review.condition_code === "paylah_account_missing" ||
    review.condition_code === "paylah_account_ambiguous";
  return (
    <>
      <div className="panel-head">
        <div>
          <Badge tone={blocking ? "blocking" : "attention"}>
            {review.severity}
          </Badge>
          <h2 style={{ marginTop: 8 }}>{reviewTitle(review.condition_code)}</h2>
        </div>
        {transaction !== undefined ? (
          <Button
            variant="ghost"
            onClick={() => {
              onOpenTransaction(transaction.id);
            }}
          >
            Open Transaction
          </Button>
        ) : null}
      </div>
      <div className={`evidence-body${fresh ? " stage-enter" : ""}`}>
        <p className={`prompt${blocking ? " is-blocking" : ""}`}>
          {evidenceBody(review, transaction)}
        </p>
        <dl className="kv">
          <dt>Financial Account</dt>
          <dd>{account}</dd>
          <dt>Amount in question</dt>
          <dd>
            {transaction === undefined
              ? "No Claims created"
              : formatUnsigned(transaction.posted_amount)}
          </dd>
          <dt>Raw source</dt>
          <dd>{raw}</dd>
          <dt>Opened</dt>
          <dd>{openedLabel(review.created_at, today)}</dd>
        </dl>
        <section>
          <h3 className="eyebrow">Claim evidence</h3>
          {claims.length === 0 ? (
            <p className="claim">No linked Claims in this Review.</p>
          ) : (
            claims.map((claim) => (
              <p className="claim" key={claim}>
                {claim}
              </p>
            ))
          )}
        </section>
        <section>
          <h3
            className="eyebrow"
            style={{ display: "block", marginBottom: 12 }}
          >
            Permitted actions
          </h3>
          <div className="review-actions">
            {categorization && transaction !== undefined ? (
              <>
                <label
                  className="sr-only"
                  htmlFor={`review-cat-${transaction.id}`}
                >
                  Category for {transaction.counterparty}
                </label>
                <select
                  className="select"
                  id={`review-cat-${transaction.id}`}
                  value={draft}
                  onChange={(event) => {
                    onDraft(transaction.id, event.target.value);
                  }}
                >
                  <option value="">Choose Category</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
                <Button
                  variant="primary"
                  disabled={draft === "" || saving === transaction.id}
                  onClick={() => {
                    onAssign(transaction);
                  }}
                >
                  {saving === transaction.id ? "Saving…" : "Assign Category"}
                </Button>
              </>
            ) : null}
            {categorization && transaction === undefined ? (
              <span className="muted">Transaction action required</span>
            ) : null}
            {needsSetup
              ? review.allowed_decisions.map((choice) => (
                  <Button key={choice} variant="primary" onClick={onOpenSetup}>
                    {decisionLabel(choice)}
                  </Button>
                ))
              : null}
            {!categorization && !needsSetup
              ? review.allowed_decisions.map((choice) => (
                  <Button
                    key={choice}
                    variant={
                      choice.includes("exclude") || choice === "keep_quarantine"
                        ? "outline"
                        : "primary"
                    }
                    disabled={saving === review.id}
                    onClick={() => {
                      onDecide(review, choice);
                    }}
                  >
                    {saving === review.id ? "Saving…" : decisionLabel(choice)}
                  </Button>
                ))
              : null}
          </div>
        </section>
      </div>
    </>
  );
}

function queueSubject(
  review: Review,
  transaction: Transaction | undefined,
): string {
  const fromContext = contextString(review.context, "subject");
  if (fromContext !== null) {
    return fromContext;
  }
  if (transaction !== undefined) {
    return `${transaction.counterparty} · ${transaction.financial_account.name}`;
  }
  return `${review.subject_type} ${review.subject_id}`;
}

function evidenceBody(
  review: Review,
  transaction: Transaction | undefined,
): string {
  const fromContext = contextString(review.context, "body");
  if (fromContext !== null) {
    return fromContext;
  }
  if (
    review.condition_code === "categorization_needed" &&
    transaction !== undefined
  ) {
    return `${transaction.counterparty} is a confirmed Transaction on ${transaction.financial_account.name}. Posted Amount is ${formatUnsigned(transaction.posted_amount)}. The statement text does not map to a Category.`;
  }
  return "Review the permitted decision.";
}
