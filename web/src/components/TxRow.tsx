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
  provisionalMark = "badge",
  density = "regular",
  onOpen,
  onToggle,
}: {
  transaction: Transaction;
  selected?: boolean;
  checked?: boolean;
  selectable?: boolean;
  provisionalMark?: "badge" | "dot";
  density?: "regular" | "compact";
  onOpen: (id: string) => void;
  onToggle?: (id: string) => void;
}) {
  const provisional = confirmationState(transaction) === "provisional";
  const transfer = !isExpense(transaction) && transaction.kind === "transfer";
  const amount = transfer
    ? formatUnsigned(activityAmount(transaction))
    : formatMoney(activityAmount(transaction), true);
  const review = needsCategorization(transaction);
  const rowClass = `tx-row${selected ? " is-selected" : ""}${density === "compact" ? " is-compact" : ""}`;

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
          {provisional && provisionalMark === "badge" ? (
            <ProvisionalBadge />
          ) : null}
          {transfer ? <Badge tone="count">Transfer</Badge> : null}
          {review ? <i className="review-dot" title="Needs review" /> : null}
        </span>
        <span className="tx-amount-side">
          {provisional && provisionalMark === "dot" ? (
            <i
              className="provisional-dot"
              title="Provisional"
              aria-label="Provisional"
            />
          ) : null}
          <strong className={`amount tx-amount${transfer ? " muted" : ""}`}>
            {amount}
          </strong>
        </span>
      </span>
    </>
  );

  if (!selectable) {
    return (
      <div className={rowClass}>
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
    <div className={rowClass}>
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
