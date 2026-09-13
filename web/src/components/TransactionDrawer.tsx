import type { Category, Transaction } from "../api";
import { CloseIcon } from "./icons";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { categoryLabel, kindLabel } from "../lib/labels";
import { formatUnsigned } from "../lib/money";
import {
  confirmationState,
  isExpense,
  needsCategorization,
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
  const categorize = isExpense(transaction);
  return (
    <>
      <div className="drawer-head">
        <div>
          <p className="eyebrow">
            {transaction.effective_date} · {transaction.financial_account.name}
          </p>
          <h2 id="drawer-title">{transaction.counterparty}</h2>
          <p
            className="hero-value amount"
            style={{ fontSize: "1.6rem", marginTop: 12 }}
          >
            {formatUnsigned(transaction.posted_amount)}
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
          <dt>Posted Amount</dt>
          <dd>{formatUnsigned(transaction.posted_amount)} SGD</dd>
          <dt>Financial Account</dt>
          <dd>{transaction.financial_account.name}</dd>
          <dt>Transaction Kind</dt>
          <dd>{kindLabel(transaction.kind)}</dd>
          <dt>Category</dt>
          <dd>
            {categoryLabel(transaction)}
            {!needsCategorization(transaction) &&
            categoryLabel(transaction) !== "Uncategorized" ? (
              <>
                {" "}
                <Badge tone="confirmed">Categorized</Badge>
              </>
            ) : null}
          </dd>
          <dt>Confirmation</dt>
          <dd>
            {confirmed
              ? "Confirmed by Statement Claim"
              : "Provisional Real-time Claim"}
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
