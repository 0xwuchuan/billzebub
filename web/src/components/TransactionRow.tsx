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
import { CategoryPill } from "./ui/CategoryPill";

export function TransactionRow({
  transaction,
  compact,
  selected = false,
  checked = false,
  selectable = false,
  onOpen,
  onToggle,
}: {
  transaction: Transaction;
  compact: boolean;
  selected?: boolean;
  checked?: boolean;
  selectable?: boolean;
  onOpen: (id: string) => void;
  onToggle?: (id: string) => void;
}) {
  const state = confirmationState(transaction);
  const transfer = !isExpense(transaction) && transaction.kind === "transfer";
  const amount = transfer
    ? formatUnsigned(activityAmount(transaction))
    : formatMoney(activityAmount(transaction), true);
  const review = needsCategorization(transaction);

  if (!selectable) {
    return (
      <button
        className={`row${selected ? " is-selected" : ""}`}
        type="button"
        onClick={() => {
          onOpen(transaction.id);
        }}
      >
        <span className="when">
          {dayMonthLabel(transaction.effective_date)}
        </span>
        <span>
          <strong>{transaction.counterparty}</strong>
          <span className="meta">
            {transaction.financial_account.name}
            {compact ? "" : ` · ${categoryLabel(transaction)}`}
          </span>
        </span>
        {transfer ? <Badge tone="count">Transfer</Badge> : null}
        {!transfer && state === "provisional" ? (
          <Badge tone="provisional">Provisional</Badge>
        ) : null}
        {!transfer && review ? (
          compact ? (
            <Badge tone="attention">Needs review</Badge>
          ) : (
            <i className="review-dot" title="Needs review" />
          )
        ) : null}
        <strong className={`amount${transfer ? " muted" : ""}`}>
          {amount}
        </strong>
      </button>
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
        <span className="tx-row-copy">
          <strong>{transaction.counterparty}</strong>
          <span className="meta">{transaction.financial_account.name}</span>
        </span>
        <CategoryPill name={categoryLabel(transaction)} />
        {transfer ? <Badge tone="count">Transfer</Badge> : null}
        {!transfer && state === "provisional" ? (
          <Badge tone="provisional">Provisional</Badge>
        ) : null}
        {review ? <i className="review-dot" title="Needs review" /> : null}
        <strong className={`amount tx-amount${transfer ? " muted" : ""}`}>
          {amount}
        </strong>
      </button>
    </div>
  );
}
