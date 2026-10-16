import { useEffect, useRef, useState, type RefObject } from "react";

import type { Category, ImportRecord, Review, Transaction } from "../api";
import { CategoryPicker } from "../components/CategoryPicker";
import {
  MerchantGroupList,
  type MerchantApplyRequest,
  type MerchantUndo,
} from "../components/MerchantGroupList";
import {
  merchantGroupsFromReviews,
  type MerchantGroupView,
} from "../lib/merchantGroups";
import { MoneyText } from "../components/MoneyText";
import { UserLabel } from "../components/UserLabel";
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
import { UNKNOWN_COUNTERPARTY, formatAccountLabel } from "../lib/identity";
import { formatUnsigned } from "../lib/money";
import type { ReviewFilter } from "../lib/route";

const CLOSED_PICKER = { open: false, query: "", index: 0 };

type PickerState = typeof CLOSED_PICKER;

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
  merchantGroups,
  suppressedReviewIds = [],
  merchantUndo = null,
  merchantSaving = false,
  onApplyMerchantGroup,
  onUndoMerchantGroup,
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
  merchantGroups?: MerchantGroupView[];
  suppressedReviewIds?: string[];
  merchantUndo?: MerchantUndo | null;
  merchantSaving?: boolean;
  onApplyMerchantGroup?: (request: MerchantApplyRequest) => void;
  onUndoMerchantGroup?: () => void;
}) {
  const [merchantPaper, setMerchantPaper] = useState(false);
  const fresh = useEntrance("review");
  const desk = useDeskMedia();
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const hidden = new Set([...hiddenIds, ...suppressedReviewIds]);
  const groups =
    merchantGroups ?? merchantGroupsFromReviews(reviews, transactions);
  const groupedReviewIds = new Set(
    groups.flatMap((group) => group.members.map((member) => member.reviewId)),
  );
  const items = filterReviews(reviews, filter).filter(
    (item) => !hidden.has(item.id) && !groupedReviewIds.has(item.id),
  );
  const selected =
    items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const selectedAssignId =
    selected === null ? null : reviewTransactionId(selected);
  const [picker, setPicker] = useState<PickerState>(CLOSED_PICKER);
  const [pickerReviewId, setPickerReviewId] = useState(selected?.id ?? "");
  if ((selected?.id ?? "") !== pickerReviewId) {
    setPickerReviewId(selected?.id ?? "");
    setPicker(CLOSED_PICKER);
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
    setPicker({ open: true, query, index: 0 });
  }

  function closePicker() {
    setPicker(CLOSED_PICKER);
    cardRef.current?.focus();
  }

  function chooseCategory(categoryId: string) {
    if (selectedAssignId !== null) {
      onDraft(selectedAssignId, categoryId);
    }
    setPicker(CLOSED_PICKER);
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
    setPicker(CLOSED_PICKER);
    onSelect(id);
    cardRef.current?.focus();
  }

  function highlightCategory(index: number) {
    setPicker((current) => ({ ...current, index }));
  }

  function appendQuery(character: string) {
    setPicker((current) => ({
      ...current,
      open: true,
      query: `${current.query}${character}`,
      index: 0,
    }));
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

  useEffect(() => {
    keyboardRef.current = {
      categories,
      picker,
      openPicker,
      closePicker,
      chooseCategory,
      moveQueue,
      highlightCategory,
      appendQuery,
      confirmCurrent,
      categorization: selected?.condition_code === "categorization_needed",
    };
  });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const snapshot = keyboardRef.current;
      if (snapshot === null || event.metaKey || event.ctrlKey || event.altKey) {
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
      <MerchantGroupList
        groups={groups}
        categories={categories}
        undo={merchantUndo}
        saving={merchantSaving}
        onApply={(request) => {
          onApplyMerchantGroup?.(request);
        }}
        onUndo={() => {
          onUndoMerchantGroup?.();
        }}
        onPaperPrimary={setMerchantPaper}
      />
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
              searchRef={searchRef}
              onPickerOpen={() => {
                openPicker("");
              }}
              onPickerQuery={(query) => {
                setPicker((current) => ({ ...current, query, index: 0 }));
              }}
              onPickerHighlight={(index) => {
                setPicker((current) => ({ ...current, index }));
              }}
              onPickerChoose={chooseCategory}
              onOpenTransaction={onOpenTransaction}
              onOpenImport={onOpenImport}
              onOpenSettings={onOpenSettings}
              quietPrimary={merchantPaper}
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
  searchRef,
  onPickerOpen,
  onPickerQuery,
  onPickerHighlight,
  onPickerChoose,
  onOpenTransaction,
  onOpenImport,
  onOpenSettings,
  quietPrimary = false,
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
  searchRef: RefObject<HTMLInputElement | null>;
  onPickerOpen: () => void;
  onPickerQuery: (query: string) => void;
  onPickerHighlight: (index: number) => void;
  onPickerChoose: (categoryId: string) => void;
  onOpenTransaction: (id: string) => void;
  onOpenImport: (id: string) => void;
  onOpenSettings: () => void;
  quietPrimary?: boolean;
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
          {categorization && assignable !== undefined ? (
            <div className="cat-picker-slot">
              <label
                className="sr-only"
                htmlFor={`review-cat-${assignable.id}`}
              >
                Category for {assignable.counterparty}
              </label>
              <CategoryPicker
                categories={categories}
                matches={filterCategories(categories, picker.query)}
                draftId={draft}
                open={picker.open}
                query={picker.query}
                activeIndex={picker.index}
                inputId={`review-cat-${assignable.id}`}
                listId={`review-cat-list-${assignable.id}`}
                searchRef={searchRef}
                onOpen={onPickerOpen}
                onQuery={onPickerQuery}
                onHighlight={onPickerHighlight}
                onChoose={onPickerChoose}
              />
            </div>
          ) : null}
          <div className="review-actions review-action-dock">
            {categorization && assignable !== undefined ? (
              <Button
                variant={quietPrimary ? "ghost" : "primary"}
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
                    variant={quietPrimary || index !== 0 ? "ghost" : "primary"}
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
                        : !quietPrimary && primaryDecision(review) === choice
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
  categories: Category[];
  picker: PickerState;
  categorization: boolean;
  openPicker: (query: string) => void;
  closePicker: () => void;
  chooseCategory: (categoryId: string) => void;
  moveQueue: (delta: number) => void;
  highlightCategory: (index: number) => void;
  appendQuery: (character: string) => void;
  confirmCurrent: () => void;
};

function filterCategories(categories: Category[], query: string): Category[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") {
    return categories;
  }
  return categories.filter((category) =>
    category.name.toLowerCase().includes(needle),
  );
}

function handlePickerKey(event: KeyboardEvent, snapshot: KeyboardSnapshot) {
  const matches = filterCategories(snapshot.categories, snapshot.picker.query);
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopImmediatePropagation();
    snapshot.closePicker();
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (matches.length === 0) {
      return;
    }
    snapshot.highlightCategory(
      Math.min(matches.length - 1, snapshot.picker.index + 1),
    );
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    event.stopImmediatePropagation();
    snapshot.highlightCategory(Math.max(0, snapshot.picker.index - 1));
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    event.stopImmediatePropagation();
    const choice = matches[snapshot.picker.index];
    if (choice !== undefined) {
      snapshot.chooseCategory(choice.id);
    }
    return;
  }
  if (!isCategorySearch(event.target) && isQueryChar(event.key, true)) {
    event.preventDefault();
    snapshot.appendQuery(event.key);
  }
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
