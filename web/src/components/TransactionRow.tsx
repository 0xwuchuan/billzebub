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

export function TransactionRow({
  transaction,
  compact,
  onOpen,
}: {
  transaction: Transaction;
  compact: boolean;
  onOpen: (id: string) => void;
}) {
  const state = confirmationState(transaction);
  const transfer = !isExpense(transaction) && transaction.kind === "transfer";
  const amount = transfer
    ? formatUnsigned(activityAmount(transaction))
    : formatMoney(activityAmount(transaction), true);
  return (
    <button
      className="row"
      type="button"
      onClick={() => {
        onOpen(transaction.id);
      }}
    >
      <span className="when">{dayMonthLabel(transaction.effective_date)}</span>
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
      {!transfer && needsCategorization(transaction) ? (
        <Badge tone="attention">Needs review</Badge>
      ) : null}
      <strong className={`amount${transfer ? " muted" : ""}`}>{amount}</strong>
    </button>
  );
}
