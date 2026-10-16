import { useEffect, useRef, useState } from "react";

import type { Category, Transaction } from "../api";
import { useOverlayMedia } from "../hooks/useOverlayMedia";
import {
  buildPickerRows,
  categoryUsage,
  chipParts,
  closedPicker,
  draftFromCategory,
  recentLeafIds,
  reducePickerKey,
  type PickerState,
} from "../lib/categoryTree";
import { CategoryPicker } from "./CategoryPicker";
import { CloseIcon } from "./icons";
import { counterpartyText } from "../lib/identity";
import { MoneyText } from "./MoneyText";
import { UserLabel } from "./UserLabel";
import { Button } from "./ui/Button";
import { CategoryChip } from "./ui/CategoryChip";
import { dayMonthLabel, kindLabel } from "../lib/labels";
import { formatUnsigned } from "../lib/money";
import {
  activityAmount,
  confirmationState,
  isExpense,
  isProvisional,
} from "../lib/workspace";

export function TransactionDrawer({
  transaction,
  categories,
  draft,
  saving,
  onDraft,
  onSave,
  onClose,
}: {
  transaction: Transaction | null;
  categories: Category[];
  draft: string;
  saving: boolean;
  onDraft: (categoryId: string) => void;
  onSave: (transaction: Transaction) => void;
  onClose: () => void;
}) {
  const overlay = useOverlayMedia();
  if (transaction === null) {
    return null;
  }
  const body = (
    <DrawerBody
      transaction={transaction}
      categories={categories}
      draft={draft}
      saving={saving}
      onDraft={onDraft}
      onSave={onSave}
      onClose={onClose}
    />
  );
  if (overlay) {
    return (
      <>
        <button
          className="drawer-backdrop open"
          type="button"
          aria-label="Close detail"
          onClick={onClose}
        />
        <aside
          className="drawer open"
          role="dialog"
          aria-modal="true"
          aria-labelledby="drawer-title"
        >
          {body}
        </aside>
      </>
    );
  }
  return (
    <aside className="tx-detail" aria-labelledby="drawer-title">
      {body}
    </aside>
  );
}

function DrawerBody({
  transaction,
  categories,
  draft,
  saving,
  onDraft,
  onSave,
  onClose,
}: {
  transaction: Transaction;
  categories: Category[];
  draft: string;
  saving: boolean;
  onDraft: (categoryId: string) => void;
  onSave: (transaction: Transaction) => void;
  onClose: () => void;
}) {
  const confirmed = confirmationState(transaction) === "confirmed";
  const provisional = isProvisional(transaction);
  const categorize = isExpense(transaction) && confirmed;
  const amount = activityAmount(transaction);
  return (
    <>
      <div className="drawer-head">
        <div className="decision-hero drawer-hero">
          <h2
            id="drawer-title"
            className={`decision-subject${transaction.counterparty.trim() === "" ? " is-unknown" : ""}`}
            dir="auto"
            title={counterpartyText(transaction.counterparty)}
          >
            {counterpartyText(transaction.counterparty)}
          </h2>
          <p className="hero-value amount drawer-amount">
            {provisional ? (
              <i
                className="provisional-dot"
                title="Provisional"
                aria-label="Provisional"
              />
            ) : null}
            <MoneyText hero text={formatUnsigned(amount)} />
          </p>
          <p className="decision-meta">
            {dayMonthLabel(transaction.effective_date)} ·{" "}
            <UserLabel
              value={transaction.financial_account.name}
              kind="account"
            />
          </p>
        </div>
        <button
          className="icon-btn"
          type="button"
          aria-label="Close"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </div>
      <div className="drawer-body">
        <dl className="kv">
          <dt>{provisional ? "Authorized Amount" : "Posted Amount"}</dt>
          <dd>{formatUnsigned(amount)}</dd>
          <dt>Financial Account</dt>
          <dd>
            <UserLabel
              value={transaction.financial_account.name}
              kind="account"
            />
          </dd>
          <dt>Transaction Kind</dt>
          <dd>{kindLabel(transaction.kind)}</dd>
          <dt>Category</dt>
          <dd>
            <AssignedChip transaction={transaction} categories={categories} />
          </dd>
          <dt>Confirmation</dt>
          <dd>
            {confirmed ? (
              <span className="confirm-status is-confirmed">
                <i className="confirm-dot" aria-hidden="true" />
                Confirmed by Statement Claim
              </span>
            ) : (
              <span className="confirm-status is-provisional">
                <i className="provisional-dot" aria-hidden="true" />
                Provisional Real-time Claim
              </span>
            )}
          </dd>
        </dl>
        {categorize ? (
          <>
            <label className="sr-only" htmlFor={`drawer-cat-${transaction.id}`}>
              Category for {transaction.counterparty}
            </label>
            <DrawerPicker
              transaction={transaction}
              categories={categories}
              draft={draft}
              inputId={`drawer-cat-${transaction.id}`}
              onDraft={onDraft}
            />
            <Button
              variant="primary"
              disabled={draft === "" || saving}
              onClick={() => {
                onSave(transaction);
              }}
            >
              {saving ? "Saving…" : "Categorize"}
            </Button>
          </>
        ) : null}
      </div>
    </>
  );
}

function AssignedChip({
  transaction,
  categories,
}: {
  transaction: Transaction;
  categories: Category[];
}) {
  const split = transaction.category_splits[0];
  if (split === undefined) {
    return <CategoryChip name="Uncategorized" />;
  }
  const parts = chipParts(categories, split.id, split.name);
  const unsure =
    parts.parentName === null &&
    categories.some(
      (category) => category.active && category.parent_id === split.id,
    ) &&
    transaction.reviews.some(
      (review) => review.condition_code === "categorization_needed",
    );
  return (
    <CategoryChip
      name={parts.name}
      parentName={parts.parentName}
      archived={parts.archived}
      unsure={unsure}
    />
  );
}

function DrawerPicker({
  transaction,
  categories,
  draft,
  inputId,
  onDraft,
}: {
  transaction: Transaction;
  categories: Category[];
  draft: string;
  inputId: string;
  onDraft: (categoryId: string) => void;
}) {
  const sheet = useOverlayMedia();
  const searchRef = useRef<HTMLInputElement>(null);
  const [picker, setPicker] = useState<PickerState>(closedPicker);
  useEffect(() => {
    if (!picker.open) {
      return;
    }
    searchRef.current?.focus();
  }, [picker.open]);
  const rows = buildPickerRows({
    categories,
    query: picker.query,
    parentId: picker.parentId,
    placing: picker.placing,
    selectedId: draft === "" ? null : draft,
    recentIds: recentLeafIds([transaction], categories),
    usage: categoryUsage([transaction]),
    allowCreate: false,
  });
  return (
    <CategoryPicker
      rows={rows}
      draft={draftFromCategory(categories, draft)}
      open={picker.open}
      query={picker.query}
      activeIndex={picker.index}
      inputId={inputId}
      listId={`${inputId}-list`}
      searchRef={searchRef}
      sheet={sheet}
      onOpen={() => {
        setPicker({ ...closedPicker, open: true });
      }}
      onDismiss={() => {
        setPicker(closedPicker);
      }}
      onQuery={(query) => {
        setPicker((current) => ({
          ...current,
          query,
          index: 0,
          parentId: query.trim() === "" ? current.parentId : null,
        }));
      }}
      onHighlight={(index) => {
        setPicker((current) => ({ ...current, index }));
      }}
      onActivate={(row) => {
        const next = reducePickerKey(
          {
            ...picker,
            index: rows.findIndex((item) => item.key === row.key),
          },
          rows,
          "Enter",
        );
        if (next.effect?.type === "assign") {
          onDraft(next.effect.categoryId);
          setPicker(closedPicker);
          return;
        }
        if (next.effect?.type === "close") {
          setPicker(closedPicker);
          return;
        }
        setPicker(next.state);
      }}
    />
  );
}
