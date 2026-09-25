import type { Transaction } from "../api";
import { categoryLabel, dayMonthLabel } from "../lib/labels";
import { formatMoney, formatUnsigned } from "../lib/money";
import {
  activityAmount,
  confirmationState,
  isExpense,
  needsCategorization,
} from "../lib/workspace";
import { Badge } from "./ui/Badge";
import { CategoryChip } from "./ui/CategoryChip";
import { ProvisionalBadge } from "./ui/ProvisionalBadge";

export function TxRow({
  transaction,
  selected = false,
  checked = false,
  selectable = false,
  onOpen,
  onToggle,
}: {
  transaction: Transaction;
  selected?: boolean;
  checked?: boolean;
  selectable?: boolean;
  onOpen: (id: string) => void;
  onToggle?: (id: string) => void;
}) {
  const provisional = confirmationState(transaction) === "provisional";
  const transfer = !isExpense(transaction) && transaction.kind === "transfer";
  const amount = transfer
    ? formatUnsigned(activityAmount(transaction))
    : formatMoney(activityAmount(transaction), true);
  const review = needsCategorization(transaction);

  const body = (
    <>
      <span className="tx-row-copy">
        <strong>{transaction.counterparty}</strong>
        <span className="meta">
          {dayMonthLabel(transaction.effective_date)}
          {" · "}
          {transaction.financial_account.name}
        </span>
      </span>
      <span className="tx-row-trailing">
        <span className="tx-row-status">
          <CategoryChip name={categoryLabel(transaction)} />
          {provisional ? <ProvisionalBadge /> : null}
          {transfer ? <Badge tone="count">Transfer</Badge> : null}
          {review ? <i className="review-dot" title="Needs review" /> : null}
        </span>
        <strong className={`amount tx-amount${transfer ? " muted" : ""}`}>
          {amount}
        </strong>
      </span>
    </>
  );

  if (!selectable) {
    return (
      <div className={`tx-row${selected ? " is-selected" : ""}`}>
        <button
          className="tx-row-main"
          type="button"
          onClick={() => {
            onOpen(transaction.id);
          }}
        >
          {body}
        </button>
      </div>
    );
  }

  return (
    <div className={`tx-row${selected ? " is-selected" : ""}`}>
      <label className="tx-check">
        <span className="sr-only">Select {transaction.counterparty}</span>
        <input
          type="checkbox"
          checked={checked}
          onChange={() => {
            onToggle?.(transaction.id);
          }}
        />
      </label>
      <button
        className="tx-row-main"
        type="button"
        onClick={() => {
          onOpen(transaction.id);
        }}
      >
        {body}
      </button>
    </div>
  );
}
