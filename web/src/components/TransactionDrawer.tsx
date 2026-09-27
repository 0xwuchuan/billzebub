import type { Category, Transaction } from "../api";
import { CloseIcon } from "./icons";
import { Button } from "./ui/Button";
import { CategoryChip } from "./ui/CategoryChip";
import { categoryLabel, dayMonthLabel, kindLabel } from "../lib/labels";
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
  const open = transaction !== null;
  return (
    <>
      <button
        className={`drawer-backdrop${open ? " open" : ""}`}
        type="button"
        tabIndex={open ? 0 : -1}
        aria-hidden={!open}
        aria-label={open ? "Close detail" : undefined}
        onClick={onClose}
      />
      <aside
        className={`drawer${open ? " open" : ""}`}
        role={open ? "dialog" : undefined}
        aria-labelledby={open ? "drawer-title" : undefined}
        aria-hidden={!open}
      >
        {transaction !== null ? (
          <DrawerBody
            transaction={transaction}
            categories={categories}
            draft={draft}
            saving={saving}
            onDraft={onDraft}
            onSave={onSave}
            onClose={onClose}
          />
        ) : null}
      </aside>
    </>
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
          <h2 id="drawer-title" className="decision-subject">
            {transaction.counterparty}
          </h2>
          <p className="hero-value amount drawer-amount">
            {provisional ? (
              <i
                className="provisional-dot"
                title="Provisional"
                aria-label="Provisional"
              />
            ) : null}
            {formatUnsigned(amount)}
          </p>
          <p className="decision-meta">
            {dayMonthLabel(transaction.effective_date)} ·{" "}
            {transaction.financial_account.name}
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
          <dd>{transaction.financial_account.name}</dd>
          <dt>Transaction Kind</dt>
          <dd>{kindLabel(transaction.kind)}</dd>
          <dt>Category</dt>
          <dd>
            <CategoryChip name={categoryLabel(transaction)} />
          </dd>
          <dt>Confirmation</dt>
          <dd>
            {confirmed ? (
              "Confirmed by Statement Claim"
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
            <label
              className="field-label"
              htmlFor={`drawer-cat-${transaction.id}`}
            >
              Category for {transaction.counterparty}
              <select
                className="select"
                id={`drawer-cat-${transaction.id}`}
                value={draft}
                onChange={(event) => {
                  onDraft(event.target.value);
                }}
              >
                <option value="">Choose Category</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
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
