import { useEffect, useRef, useState, type RefObject } from "react";

import type { Category, ImportRecord, Review, Transaction } from "../api";
import { CategoryPicker } from "../components/CategoryPicker";
import { MoneyText } from "../components/MoneyText";
import { UserLabel } from "../components/UserLabel";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { CategoryChip } from "../components/ui/CategoryChip";
import { useDeskMedia } from "../hooks/useDeskMedia";
import { useOverlayMedia } from "../hooks/useOverlayMedia";
import { useEntrance } from "../hooks/useEntrance";
import {
  buildPickerRows,
  categoryUsage,
  childCategories,
  compareCategoryNames,
  closedPicker,
  draftFromCategory,
  recentLeafIds,
  reducePickerKey,
  type PickerRow,
  type PickerState,
} from "../lib/categoryTree";
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
import { UNKNOWN_COUNTERPARTY, formatAccountLabel } from "../lib/identity";
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
  onApply,
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
  onApply?: (
    transaction: Transaction,
    categoryId: string,
  ) => void | Promise<boolean | void>;
  onDecide: (review: Review, choice: string) => void | Promise<boolean | void>;
  onOpenTransaction: (id: string) => void;
  onOpenImport: (id: string) => void;
  onOpenSettings: () => void;
}) {
  const fresh = useEntrance("review");
  const desk = useDeskMedia();
  const sheet = useOverlayMedia();
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const hidden = new Set(hiddenIds);
  const items = filterReviews(reviews, filter).filter(
    (item) => !hidden.has(item.id),
  );
  const selected =
    items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const selectedAssignId =
    selected === null ? null : reviewTransactionId(selected);
  const [picker, setPicker] = useState<PickerState>(closedPicker);
  const [pickerReviewId, setPickerReviewId] = useState(selected?.id ?? "");
  if ((selected?.id ?? "") !== pickerReviewId) {
    setPickerReviewId(selected?.id ?? "");
    setPicker(closedPicker);
  }
  const cardRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const keyboardRef = useRef<KeyboardSnapshot | null>(null);

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

  function openPicker(query: string) {
    setPicker({ ...closedPicker, open: true, query });
  }

  function closePicker() {
    setPicker(closedPicker);
    cardRef.current?.focus();
  }

  function chooseCategory(categoryId: string) {
    if (selectedAssignId !== null) {
      onDraft(selectedAssignId, categoryId);
    }
    setPicker(closedPicker);
    cardRef.current?.focus();
  }

  function moveQueue(delta: number) {
    const index = items.findIndex((item) => item.id === selected?.id);
    const start = index < 0 ? 0 : index;
    const next = Math.min(items.length - 1, Math.max(0, start + delta));
    const id = items[next]?.id;
    if (id === undefined || id === selected?.id) {
      return;
    }
    setPicker(closedPicker);
    onSelect(id);
    cardRef.current?.focus();
  }

  function appendQuery(character: string) {
    setPicker((current) => ({
      ...current,
      open: true,
      query: `${current.query}${character}`,
      index: 0,
      parentId: null,
      placing: false,
    }));
  }

  function rowsFor(state: PickerState): PickerRow[] {
    return buildPickerRows({
      categories,
      query: state.query,
      parentId: state.parentId,
      placing: state.placing,
      selectedId:
        selectedAssignId === null ? null : (drafts[selectedAssignId] ?? null),
      recentIds: recentLeafIds(transactions, categories),
      usage: categoryUsage(transactions),
      allowCreate: onApply !== undefined,
    });
  }

  function applyPickerResult(next: ReturnType<typeof reducePickerKey>) {
    if (next.effect?.type === "close") {
      closePicker();
      return;
    }
    if (next.effect?.type === "assign") {
      chooseCategory(next.effect.categoryId);
      return;
    }
    if (next.effect?.type === "create") {
      closePicker();
      return;
    }
    setPicker(next.state);
  }

  function confirmCurrent() {
    if (selected === null || isSetupReview(selected)) {
      return;
    }
    if (selected.condition_code === "categorization_needed") {
      const assignable =
        transactionForReview(selected, transactions) ??
        transactionFromReviewContext(selected);
      if (assignable === undefined) {
        return;
      }
      const draftId =
        selectedAssignId === null ? "" : (drafts[selectedAssignId] ?? "");
      const fallback = parentFallback(selected, categories, transactions);
      if (draftId === "" && fallback !== null) {
        keepParent(fallback.parent.id);
        return;
      }
      if (draftId === "") {
        openPicker("");
        return;
      }
      assignAndAdvance(assignable);
      return;
    }
    const choice = primaryDecision(selected);
    if (choice !== null) {
      decideAndAdvance(selected, choice);
    }
  }

  function keepParent(parentId: string) {
    if (selected === null) {
      return;
    }
    const assignable =
      transactionForReview(selected, transactions) ??
      transactionFromReviewContext(selected);
    if (assignable === undefined) {
      return;
    }
    const already = assignable.category_splits.some(
      (split) => split.id === parentId,
    );
    if (already && selected.allowed_decisions.includes("keep")) {
      decideAndAdvance(selected, "keep");
      return;
    }
    applyCategory(assignable, parentId);
  }

  function applyCategory(transaction: Transaction, categoryId: string) {
    if (selected === null) {
      return;
    }
    if (onApply === undefined) {
      chooseCategory(categoryId);
      return;
    }
    const reviewId = selected.id;
    advancePast(reviewId);
    void Promise.resolve(onApply(transaction, categoryId)).then((result) => {
      finishAdvance(reviewId, result);
    });
  }

  useEffect(() => {
    const fallback =
      selected === null
        ? null
        : parentFallback(selected, categories, transactions);
    keyboardRef.current = {
      picker,
      rows: rowsFor(picker),
      openPicker,
      closePicker,
      moveQueue,
      appendQuery,
      confirmCurrent,
      applyPickerResult,
      keepParent,
      applyChild: (categoryId: string) => {
        const assignable =
          selected === null
            ? undefined
            : (transactionForReview(selected, transactions) ??
              transactionFromReviewContext(selected));
        if (assignable !== undefined) {
          applyCategory(assignable, categoryId);
        }
      },
      fallbackChildIds: fallback?.children.map((child) => child.id) ?? [],
      categorization: selected?.condition_code === "categorization_needed",
    };
  });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const snapshot = keyboardRef.current;
      if (
        snapshot === null ||
        event.metaKey ||
        event.ctrlKey ||
        (event.altKey && event.key !== "Enter")
      ) {
        return;
      }
      if (event.isComposing || isTextEntry(event.target)) {
        return;
      }
      const searchFocused = isCategorySearch(event.target);
      if (searchFocused) {
        handlePickerKey(event, snapshot);
        return;
      }
      if (snapshot.picker.open) {
        handlePickerKey(event, snapshot);
        return;
      }
      if (
        snapshot.fallbackChildIds.length > 0 &&
        (event.key === "1" || event.key === "2" || event.key === "3")
      ) {
        const childId = snapshot.fallbackChildIds[Number(event.key) - 1];
        if (childId !== undefined) {
          event.preventDefault();
          snapshot.applyChild(childId);
        }
        return;
      }
      if (
        snapshot.fallbackChildIds.length > 0 &&
        (event.key === "k" || event.key === "K")
      ) {
        event.preventDefault();
        snapshot.confirmCurrent();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "j") {
        event.preventDefault();
        snapshot.moveQueue(1);
        return;
      }
      if (event.key === "ArrowUp" || event.key === "k") {
        event.preventDefault();
        snapshot.moveQueue(-1);
        return;
      }
      if (!onDecisionCard(event.target)) {
        return;
      }
      if (event.key === "Enter" && !isActivationTarget(event.target)) {
        event.preventDefault();
        snapshot.confirmCurrent();
        return;
      }
      if (!snapshot.categorization) {
        return;
      }
      if (event.key === "/") {
        event.preventDefault();
        snapshot.openPicker("");
        return;
      }
      if (isQueryChar(event.key, false)) {
        event.preventDefault();
        snapshot.openPicker(event.key);
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
    };
  }, []);

  useEffect(() => {
    if (!picker.open) {
      return;
    }
    const field = searchRef.current;
    if (field === null) {
      return;
    }
    field.focus();
    const end = field.value.length;
    field.setSelectionRange(end, end);
  }, [picker.open]);

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
          ref={cardRef}
          id="review-decision"
          className={`card evidence-pane${selected === null ? " is-empty" : ""}`}
          aria-live="polite"
          aria-label="Review decision"
          tabIndex={-1}
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
              onAssign={assignAndAdvance}
              onDecide={decideAndAdvance}
              picker={picker}
              sheet={sheet}
              searchRef={searchRef}
              transactions={transactions}
              onPickerOpen={() => {
                openPicker("");
              }}
              onPickerDismiss={closePicker}
              onPickerQuery={(query) => {
                setPicker((current) => ({
                  ...current,
                  query,
                  index: 0,
                  parentId: query.trim() === "" ? current.parentId : null,
                  placing: false,
                }));
              }}
              onPickerHighlight={(index) => {
                setPicker((current) => ({ ...current, index }));
              }}
              onPickerActivate={(row) => {
                applyPickerResult(
                  reducePickerKey(
                    {
                      ...picker,
                      index: rowsFor(picker).findIndex(
                        (item) => item.key === row.key,
                      ),
                    },
                    rowsFor(picker),
                    "Enter",
                  ),
                );
              }}
              onApplyChild={(categoryId) => {
                const assignable =
                  transactionForReview(selected, transactions) ??
                  transactionFromReviewContext(selected);
                if (assignable !== undefined) {
                  applyCategory(assignable, categoryId);
                }
              }}
              onKeepParent={keepParent}
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
  const title = queueTitle(review, transaction, importRecord);
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
          <UserLabel value={title === UNKNOWN_COUNTERPARTY ? "" : title} />
        </span>
        <span className="queue-reason">
          {openedLabel(review.created_at, today)}
        </span>
      </span>
      <span className="queue-right">
        <span className="amount">
          {amount === null ? (
            queueFallbackAmount(review)
          ) : (
            <MoneyText text={amount} />
          )}
        </span>
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
  onAssign,
  onDecide,
  picker,
  sheet,
  searchRef,
  transactions,
  onPickerOpen,
  onPickerDismiss,
  onPickerQuery,
  onPickerHighlight,
  onPickerActivate,
  onApplyChild,
  onKeepParent,
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
  onAssign: (transaction: Transaction) => void;
  onDecide: (review: Review, choice: string) => void;
  picker: PickerState;
  sheet: boolean;
  searchRef: RefObject<HTMLInputElement | null>;
  transactions: Transaction[];
  onPickerOpen: () => void;
  onPickerDismiss: () => void;
  onPickerQuery: (query: string) => void;
  onPickerHighlight: (index: number) => void;
  onPickerActivate: (row: PickerRow) => void;
  onApplyChild: (categoryId: string) => void;
  onKeepParent: (parentId: string) => void;
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
  const fallback = categorization
    ? parentFallback(review, categories, transactions)
    : null;
  const pickerRows = buildPickerRows({
    categories,
    query: picker.query,
    parentId: picker.parentId,
    placing: picker.placing,
    selectedId: draft === "" ? null : draft,
    recentIds: recentLeafIds(transactions, categories),
    usage: categoryUsage(transactions),
    allowCreate: false,
  });
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
  const when =
    transaction !== undefined
      ? dayMonthLabel(transaction.effective_date)
      : contextString(review.context, "effective_date") !== null
        ? dayMonthLabel(contextString(review.context, "effective_date") ?? "")
        : null;
  const accountShown = account === "" ? "" : formatAccountLabel(account);
  const factParts = [
    account,
    when,
    openedLabel(review.created_at, today),
  ].filter((part): part is string => part !== null && part !== "");
  const shownParts = [
    accountShown,
    when,
    openedLabel(review.created_at, today),
  ].filter((part): part is string => part !== null && part !== "");
  const facts = factParts.join(" · ");
  const factsShown = shownParts.join(" · ");
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
          <h2
            className={`decision-subject${subject === UNKNOWN_COUNTERPARTY ? " is-unknown" : ""}`}
            dir="auto"
            title={subject}
          >
            {subject === UNKNOWN_COUNTERPARTY ? (
              subject
            ) : (
              <UserLabel value={subject} />
            )}
          </h2>
          {amount !== null ? (
            <p className="decision-amount amount">
              <MoneyText hero text={amount} />
            </p>
          ) : null}
          <p className="decision-meta" title={facts}>
            {factsShown}
            {jevLine !== null ? (
              <span className="decision-meta-jev">{jevLine}</span>
            ) : null}
          </p>
        </div>
        <section className="review-decision">
          {categorization && assignable !== undefined && fallback !== null ? (
            <ParentFallbackCard
              parent={fallback.parent}
              picks={fallback.children}
              onPick={onApplyChild}
            />
          ) : null}
          {categorization && assignable !== undefined && fallback === null ? (
            <div className="cat-picker-slot">
              <label
                className="sr-only"
                htmlFor={`review-cat-${assignable.id}`}
              >
                Category for {assignable.counterparty}
              </label>
              <CategoryPicker
                rows={pickerRows}
                draft={draftFromCategory(categories, draft)}
                open={picker.open}
                query={picker.query}
                activeIndex={picker.index}
                inputId={`review-cat-${assignable.id}`}
                listId={`review-cat-list-${assignable.id}`}
                searchRef={searchRef}
                sheet={sheet}
                onOpen={onPickerOpen}
                onDismiss={onPickerDismiss}
                onQuery={onPickerQuery}
                onHighlight={onPickerHighlight}
                onActivate={onPickerActivate}
              />
            </div>
          ) : null}
          <div className="review-actions review-action-dock">
            {categorization && assignable !== undefined && fallback !== null ? (
              <Button
                variant="primary"
                title={`Keep ${fallback.parent.name}`}
                disabled={saving === assignable.id}
                onClick={() => {
                  onKeepParent(fallback.parent.id);
                }}
              >
                <span className="decision-choice">
                  {saving === assignable.id
                    ? "Saving…"
                    : `Keep ${fallback.parent.name}`}
                </span>
              </Button>
            ) : null}
            {categorization && assignable !== undefined && fallback === null ? (
              <Button
                variant="primary"
                title="Assign Category"
                disabled={draft === "" || saving === assignable.id}
                onClick={() => {
                  onAssign(assignable);
                }}
              >
                <span className="decision-choice">
                  {saving === assignable.id ? "Saving…" : "Assign Category"}
                </span>
              </Button>
            ) : null}
            {needsSetup
              ? review.allowed_decisions.map((choice, index) => (
                  <Button
                    key={choice}
                    variant={index === 0 ? "primary" : "ghost"}
                    title={decisionLabel(choice)}
                    onClick={onOpenSettings}
                  >
                    <span className="decision-choice">
                      {decisionLabel(choice)}
                    </span>
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
                        : primaryDecision(review) === choice
                          ? "primary"
                          : "ghost"
                    }
                    title={decisionLabel(choice)}
                    disabled={saving === review.id}
                    onClick={() => {
                      onDecide(review, choice);
                    }}
                  >
                    <span className="decision-choice">
                      {saving === review.id ? "Saving…" : decisionLabel(choice)}
                    </span>
                  </Button>
                ))
              : null}
          </div>
          <ShortcutList
            categorization={categorization}
            canAssign={categorization && draft !== ""}
            confirmLabel={confirmShortcutLabel(
              review,
              categorization,
              needsSetup,
            )}
          />
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
        </section>
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
    return transaction.counterparty.trim() === ""
      ? UNKNOWN_COUNTERPARTY
      : transaction.counterparty;
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
    return "Unknown counterparty";
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

type KeyboardSnapshot = {
  picker: PickerState;
  rows: PickerRow[];
  categorization: boolean;
  fallbackChildIds: string[];
  openPicker: (query: string) => void;
  closePicker: () => void;
  moveQueue: (delta: number) => void;
  appendQuery: (character: string) => void;
  confirmCurrent: () => void;
  applyPickerResult: (next: ReturnType<typeof reducePickerKey>) => void;
  keepParent: (parentId: string) => void;
  applyChild: (categoryId: string) => void;
};

function parentFallback(
  review: Review,
  categories: Category[],
  transactions: Transaction[],
): { parent: Category; children: Category[] } | null {
  if (review.context.jev_parent_fallback !== true) {
    return null;
  }
  const suggested = contextString(review.context, "suggested_category_id");
  const attempt = jevAttemptFromContext(review.context);
  const categoryId = suggested ?? attempt?.category_id ?? null;
  if (categoryId === null) {
    return null;
  }
  const parent = categories.find(
    (category) => category.id === categoryId && category.parent_id === null,
  );
  if (parent === undefined) {
    return null;
  }
  const usage = categoryUsage(transactions);
  const children = childCategories(categories, parent.id)
    .sort(
      (left, right) =>
        (usage.get(right.id) ?? 0) - (usage.get(left.id) ?? 0) ||
        compareCategoryNames(left.name, right.name),
    )
    .slice(0, 3);
  if (children.length === 0) {
    return null;
  }
  return { parent, children };
}

function ParentFallbackCard({
  parent,
  picks,
  onPick,
}: {
  parent: Category;
  picks: Category[];
  onPick: (categoryId: string) => void;
}) {
  return (
    <div className="cat-fallback">
      <CategoryChip name={parent.name} unsure />
      <p className="cat-fallback-prompt">Pick a subcategory?</p>
      <div className="cat-fallback-picks">
        {picks.map((child, index) => (
          <button
            key={child.id}
            className="btn btn-ghost cat-fallback-pick"
            type="button"
            onClick={() => {
              onPick(child.id);
            }}
          >
            <span className="cat-fallback-key">{index + 1}</span>
            {child.name}
          </button>
        ))}
      </div>
    </div>
  );
}

function handlePickerKey(event: KeyboardEvent, snapshot: KeyboardSnapshot) {
  const navigation = new Set([
    "Escape",
    "ArrowDown",
    "ArrowUp",
    "ArrowLeft",
    "ArrowRight",
    "Enter",
    "Backspace",
  ]);
  if (!navigation.has(event.key)) {
    if (!isCategorySearch(event.target) && isQueryChar(event.key, true)) {
      event.preventDefault();
      snapshot.appendQuery(event.key);
    }
    return;
  }
  if (event.key === "Backspace" && snapshot.picker.query !== "") {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  snapshot.applyPickerResult(
    reducePickerKey(snapshot.picker, snapshot.rows, event.key, {
      alt: event.altKey,
    }),
  );
}

function ShortcutList({
  categorization,
  canAssign,
  confirmLabel,
}: {
  categorization: boolean;
  canAssign: boolean;
  confirmLabel: string | null;
}) {
  const enter = categorization
    ? canAssign
      ? "assign and next"
      : "open category search"
    : confirmLabel === null
      ? null
      : `${confirmLabel} and next`;
  return (
    <ul className="review-shortcuts" aria-label="Keyboard shortcuts">
      {enter === null ? null : (
        <li>
          <kbd>Enter</kbd> {enter}
        </li>
      )}
      <li>
        <kbd>↑</kbd>
        <kbd>↓</kbd> or <kbd>j</kbd>
        <kbd>k</kbd> move queue
      </li>
      {categorization ? (
        <>
          <li>
            <kbd>/</kbd> or type-ahead opens category search
          </li>
          <li>
            <kbd>↑</kbd>
            <kbd>↓</kbd> in search move matches
          </li>
          <li>
            <kbd>Enter</kbd> in search chooses the Category
          </li>
          <li>
            <kbd>Esc</kbd> closes search
          </li>
        </>
      ) : null}
    </ul>
  );
}

function confirmShortcutLabel(
  review: Review,
  categorization: boolean,
  needsSetup: boolean,
): string | null {
  if (categorization || needsSetup) {
    return null;
  }
  const choice = primaryDecision(review);
  return choice === null ? null : decisionLabel(choice);
}

function primaryDecision(review: Review): string | null {
  return (
    review.allowed_decisions.find(
      (choice) => !choice.includes("exclude") && choice !== "keep_quarantine",
    ) ?? null
  );
}

function isSetupReview(review: Review): boolean {
  return (
    review.condition_code === "apple_wallet_unmapped_card" ||
    review.condition_code === "paylah_account_missing" ||
    review.condition_code === "paylah_account_ambiguous"
  );
}

function isCategorySearch(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.dataset.catSearch === "true";
}

function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement) || isCategorySearch(target)) {
    return false;
  }
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function isActivationTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("button, a") !== null;
}

function onDecisionCard(target: EventTarget | null): boolean {
  if (
    target === window ||
    target === document ||
    target === document.body ||
    target === document.documentElement
  ) {
    return true;
  }
  if (!(target instanceof Node)) {
    return false;
  }
  return document.getElementById("review-decision")?.contains(target) ?? false;
}

function isQueryChar(key: string, allowVim: boolean): boolean {
  if (key.length !== 1 || !/[a-z0-9]/i.test(key)) {
    return false;
  }
  if (!allowVim && (key === "j" || key === "k" || key === "J" || key === "K")) {
    return false;
  }
  return true;
}
