import { useState } from "react";

import type { Category, ImportRecord, Review, Transaction } from "../api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useDeskMedia } from "../hooks/useDeskMedia";
import { useEntrance } from "../hooks/useEntrance";
import {
  activityAmount,
  categorizationAmount,
  categorizationCounterparty,
  contextString,
  contextStrings,
  filterReviews,
  importForReview,
  jevAttemptFromContext,
  type JevAttempt,
  nextPendingReviewId,
  reviewTransactionId,
  transactionForReview,
  transactionFromReviewContext,
} from "../lib/workspace";
import {
  dayMonthLabel,
  decisionLabel,
  openedLabel,
  reviewTitle,
} from "../lib/labels";
import { formatUnsigned } from "../lib/money";
import type { ReviewFilter } from "../lib/route";

export function ReviewPage({
  reviews,
  transactions,
  imports,
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
  onOpenImport,
  onOpenSettings,
}: {
  reviews: Review[];
  transactions: Transaction[];
  imports: ImportRecord[];
  categories: Category[];
  filter: ReviewFilter;
  selectedId: string;
  drafts: Record<string, string>;
  saving: string | null;
  today: Date;
  onFilter: (filter: ReviewFilter) => void;
  onSelect: (id: string) => void;
  onDraft: (transactionId: string, categoryId: string) => void;
  onAssign: (transaction: Transaction) => void | Promise<boolean | void>;
  onDecide: (review: Review, choice: string) => void | Promise<boolean | void>;
  onOpenTransaction: (id: string) => void;
  onOpenImport: (id: string) => void;
  onOpenSettings: () => void;
}) {
  const fresh = useEntrance("review");
  const desk = useDeskMedia();
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const hidden = new Set(hiddenIds);
  const items = filterReviews(reviews, filter).filter(
    (item) => !hidden.has(item.id),
  );
  const selected =
    items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const selectedAssignId =
    selected === null ? null : reviewTransactionId(selected);

  function advancePast(reviewId: string) {
    onSelect(nextPendingReviewId(items, reviewId));
    const live = new Set(reviews.map((review) => review.id));
    setHiddenIds((current) => {
      const next = current.filter((id) => live.has(id));
      return next.includes(reviewId) ? next : [...next, reviewId];
    });
  }

  function restore(reviewId: string) {
    setHiddenIds((current) => current.filter((id) => id !== reviewId));
    onSelect(reviewId);
  }

  function finishAdvance(
    reviewId: string,
    result: boolean | void,
  ): boolean | void {
    if (result === false) {
      restore(reviewId);
    }
    return result;
  }

  function assignAndAdvance(transaction: Transaction) {
    if (selected === null) {
      return;
    }
    const reviewId = selected.id;
    advancePast(reviewId);
    void Promise.resolve(onAssign(transaction)).then((result) => {
      finishAdvance(reviewId, result);
    });
  }

  function decideAndAdvance(review: Review, choice: string) {
    advancePast(review.id);
    void Promise.resolve(onDecide(review, choice)).then((result) => {
      finishAdvance(review.id, result);
    });
  }

  return (
    <div className={`review-page${fresh ? " stage-enter" : ""}`}>
      <div className="filters">
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
        <span className="muted review-queue-count">
          {items.length} open · blocking first
        </span>
      </div>
      <div className={`desk review-desk${desk ? "" : " is-card-flow"}`}>
        {desk ? (
          <section
            className="card queue-pane"
            aria-label="Pending Review queue"
          >
            <div className="panel-head">
              <h2>Queue</h2>
              <span className="muted" style={{ fontSize: "var(--bz-text-sm)" }}>
                {items.length} open
              </span>
            </div>
            {items.length === 0 ? (
              <p className="empty">
                No Pending Review in this filter. Confirmed history is up to
                date.
              </p>
            ) : (
              <div className="queue-list">
                {items.map((item) => (
                  <QueueItem
                    key={item.id}
                    review={item}
                    transaction={transactionForReview(item, transactions)}
                    importRecord={importForReview(item, imports)}
                    current={selected !== null && selected.id === item.id}
                    today={today}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            )}
          </section>
        ) : null}
        <section
          className={`card evidence-pane${selected === null ? " is-empty" : ""}`}
          aria-live="polite"
          aria-label="Review decision"
        >
          {selected === null ? (
            <p className="empty">
              Nothing to decide. Pick another filter or come back after the next
              Extraction.
            </p>
          ) : (
            <Evidence
              review={selected}
              transaction={transactionForReview(selected, transactions)}
              importRecord={importForReview(selected, imports)}
              categories={categories}
              draft={
                selectedAssignId === null
                  ? ""
                  : (drafts[selectedAssignId] ?? "")
              }
              saving={saving}
              today={today}
              remaining={items.length}
              onDraft={onDraft}
              onAssign={assignAndAdvance}
              onDecide={decideAndAdvance}
              onOpenTransaction={onOpenTransaction}
              onOpenImport={onOpenImport}
              onOpenSettings={onOpenSettings}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function QueueItem({
  review,
  transaction,
  importRecord,
  current,
  today,
  onSelect,
}: {
  review: Review;
  transaction: Transaction | undefined;
  importRecord: ImportRecord | undefined;
  current: boolean;
  today: Date;
  onSelect: (id: string) => void;
}) {
  const blocking = review.severity === "blocking";
  const amountMoney =
    transaction === undefined
      ? categorizationAmount(review.context)
      : activityAmount(transaction);
  const amount = amountMoney === null ? null : formatUnsigned(amountMoney);
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
          {queueTitle(review, transaction, importRecord)}
        </span>
        <span className="queue-reason">
          {openedLabel(review.created_at, today)}
        </span>
      </span>
      <span className="queue-right">
        <span className="amount">{amount ?? queueFallbackAmount(review)}</span>
      </span>
    </button>
  );
}

function Evidence({
  review,
  transaction,
  importRecord,
  categories,
  draft,
  saving,
  today,
  remaining,
  onDraft,
  onAssign,
  onDecide,
  onOpenTransaction,
  onOpenImport,
  onOpenSettings,
}: {
  review: Review;
  transaction: Transaction | undefined;
  importRecord: ImportRecord | undefined;
  categories: Category[];
  draft: string;
  saving: string | null;
  today: Date;
  remaining: number;
  onDraft: (transactionId: string, categoryId: string) => void;
  onAssign: (transaction: Transaction) => void;
  onDecide: (review: Review, choice: string) => void;
  onOpenTransaction: (id: string) => void;
  onOpenImport: (id: string) => void;
  onOpenSettings: () => void;
}) {
  const fresh = useEntrance(`review:${review.id}`);
  const blocking = review.severity === "blocking";
  const claims = contextStrings(review.context, "claims");
  const assignable = transaction ?? transactionFromReviewContext(review);
  const raw =
    contextString(review.context, "raw") ??
    assignable?.counterparty ??
    review.subject_id;
  const account =
    contextString(review.context, "account") ??
    assignable?.financial_account.name ??
    importRecord?.financial_account_name ??
    (review.condition_code === "categorization_needed"
      ? ""
      : review.subject_type);
  const categorization = review.condition_code === "categorization_needed";
  const jevAttempt = categorization
    ? jevAttemptFromContext(review.context)
    : null;
  const jevLine = jevDecisionLine(jevAttempt);
  const needsSetup =
    review.condition_code === "apple_wallet_unmapped_card" ||
    review.condition_code === "paylah_account_missing" ||
    review.condition_code === "paylah_account_ambiguous";
  const amountMoney =
    transaction !== undefined
      ? activityAmount(transaction)
      : categorizationAmount(review.context);
  const amount = amountMoney === null ? null : formatUnsigned(amountMoney);
  const subject = decisionSubject(review, assignable, importRecord);
  const meta = [
    account,
    transaction !== undefined
      ? dayMonthLabel(transaction.effective_date)
      : contextString(review.context, "effective_date") !== null
        ? dayMonthLabel(contextString(review.context, "effective_date") ?? "")
        : null,
    openedLabel(review.created_at, today),
  ]
    .filter((part): part is string => part !== null && part !== "")
    .join(" · ");
  return (
    <>
      <div className="panel-head">
        <div className="decision-badges">
          <Badge tone={blocking ? "blocking" : "attention"}>
            {review.severity}
          </Badge>
          <Badge tone={blocking ? "blocking" : "attention"}>
            {reviewTitle(review.condition_code)}
          </Badge>
          <span className="muted review-remaining">{remaining} left</span>
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
        ) : importRecord !== undefined ? (
          <Button
            variant="ghost"
            onClick={() => {
              onOpenImport(importRecord.id);
            }}
          >
            Open Import
          </Button>
        ) : null}
      </div>
      <div className={`evidence-body${fresh ? " stage-enter" : ""}`}>
        <div className="decision-hero">
          <h2 className="decision-subject">{subject}</h2>
          {amount !== null ? (
            <p className="decision-amount amount">{amount}</p>
          ) : null}
          <p className="decision-meta">{meta}</p>
          {jevLine !== null ? <p className="decision-meta">{jevLine}</p> : null}
        </div>
        <section className="review-decision">
          <div className="review-actions">
            {categorization && assignable !== undefined ? (
              <>
                <label
                  className="sr-only"
                  htmlFor={`review-cat-${assignable.id}`}
                >
                  Category for {assignable.counterparty}
                </label>
                <select
                  className="select"
                  id={`review-cat-${assignable.id}`}
                  value={draft}
                  onChange={(event) => {
                    onDraft(assignable.id, event.target.value);
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
                  disabled={draft === "" || saving === assignable.id}
                  onClick={() => {
                    onAssign(assignable);
                  }}
                >
                  {saving === assignable.id ? "Saving…" : "Assign Category"}
                </Button>
              </>
            ) : null}
            {needsSetup
              ? review.allowed_decisions.map((choice) => (
                  <Button
                    key={choice}
                    variant="primary"
                    onClick={onOpenSettings}
                  >
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
        {categorization ? null : (
          <details className="import-details review-details">
            <summary>Review details</summary>
            <p className={`prompt${blocking ? " is-blocking" : ""}`}>
              {evidenceBody(review, transaction)}
            </p>
            {jevAttempt !== null ? (
              <section>
                <h3 className="eyebrow">Last Jev attempt</h3>
                <dl className="kv">
                  <dt>Action</dt>
                  <dd>{jevAttempt.action}</dd>
                  <dt>Choice</dt>
                  <dd>{jevAttempt.choice ?? "none"}</dd>
                  <dt>Confidence</dt>
                  <dd>{jevAttempt.choice_confidence ?? "—"}</dd>
                  <dt>Evidence noul</dt>
                  <dd>{jevAttempt.noul ?? "—"}</dd>
                  <dt>Category</dt>
                  <dd>
                    {jevAttempt.action === "apply"
                      ? (jevAttempt.category_name ?? "—")
                      : "skip"}
                  </dd>
                  <dt>Model</dt>
                  <dd>{jevAttempt.model}</dd>
                  {jevAttempt.error_class !== null ? (
                    <>
                      <dt>TypeSafe error</dt>
                      <dd>
                        {jevAttempt.error_class}
                        {jevAttempt.error_message !== null
                          ? `: ${jevAttempt.error_message}`
                          : ""}
                      </dd>
                    </>
                  ) : null}
                </dl>
              </section>
            ) : null}
            <dl className="kv">
              <dt>Condition</dt>
              <dd>{review.condition_code}</dd>
              <dt>Review</dt>
              <dd>{review.id}</dd>
              <dt>Subject</dt>
              <dd>
                {review.subject_type} {review.subject_id}
              </dd>
              <dt>Financial Account</dt>
              <dd>{account}</dd>
              <dt>Amount in question</dt>
              <dd>{amount ?? "No Claims created"}</dd>
              <dt>Raw source</dt>
              <dd>{raw}</dd>
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
          </details>
        )}
      </div>
    </>
  );
}

function queueTitle(
  review: Review,
  transaction: Transaction | undefined,
  importRecord: ImportRecord | undefined,
): string {
  return decisionSubject(review, transaction, importRecord);
}

function queueFallbackAmount(review: Review): string {
  const money = categorizationAmount(review.context);
  if (money !== null) {
    return formatUnsigned(money);
  }
  if (
    review.subject_type === "source_artifact" ||
    review.subject_type === "extraction"
  ) {
    return "Source Artifact";
  }
  return "—";
}

function decisionSubject(
  review: Review,
  transaction: Transaction | undefined,
  importRecord: ImportRecord | undefined,
): string {
  if (transaction !== undefined) {
    return transaction.counterparty;
  }
  const fromContext = categorizationCounterparty(review.context);
  if (fromContext !== null) {
    return fromContext;
  }
  if (importRecord?.financial_account_name != null) {
    return importRecord.financial_account_name;
  }
  if (importRecord?.adapter_key != null) {
    return importRecord.adapter_key;
  }
  if (review.condition_code === "categorization_needed") {
    return "Unknown Counterparty";
  }
  return reviewTitle(review.condition_code);
}

function jevDecisionLine(attempt: JevAttempt | null): string | null {
  if (attempt === null || attempt.choice === null) {
    return null;
  }
  const parts = [`Jev ${attempt.action}`, attempt.choice];
  if (attempt.choice_confidence !== null) {
    parts.push(attempt.choice_confidence);
  }
  return parts.join(" · ");
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
