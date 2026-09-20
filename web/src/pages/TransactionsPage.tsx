import { useState } from "react";

import type { Category, Transaction } from "../api";
import { TransactionRow } from "../components/TransactionRow";
import { Button } from "../components/ui/Button";
import { PlusIcon } from "../components/icons";
import { useEntrance } from "../hooks/useEntrance";
import { centsToMoney, formatUnsigned } from "../lib/money";
import type { ConfirmationFilter } from "../lib/route";
import {
  canCategorize,
  filterSummary,
  filterTransactions,
  groupSpentCents,
  groupTransactions,
  sortTransactions,
} from "../lib/workspace";

export function TransactionsPage({
  transactions,
  categories,
  accounts,
  confirmation,
  category,
  accountId,
  selectedId,
  today,
  loadingMore,
  hasMore,
  saving,
  onConfirmation,
  onCategory,
  onAccount,
  onOpen,
  onLoadMore,
  onCategorizeMany,
}: {
  transactions: Transaction[];
  categories: Category[];
  accounts: Array<{ id: string; name: string }>;
  confirmation: ConfirmationFilter;
  category: string;
  accountId: string;
  selectedId: string | null;
  today: Date;
  loadingMore: boolean;
  hasMore: boolean;
  saving: string | null;
  onConfirmation: (value: ConfirmationFilter) => void;
  onCategory: (value: string) => void;
  onAccount: (value: string) => void;
  onOpen: (id: string) => void;
  onLoadMore: () => void;
  onCategorizeMany: (ids: string[], categoryId: string) => Promise<void>;
}) {
  const fresh = useEntrance("transactions");
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkCategory, setBulkCategory] = useState("");
  const rows = sortTransactions(
    filterTransactions({
      items: transactions,
      query,
      accountId,
      category,
      confirmation,
    }),
  );
  const groups = groupTransactions(rows, today);
  const summary = filterSummary(rows);
  const selectedSet = new Set(selected);
  const chips = [
    ["", "All"],
    ["confirmed", "Confirmed"],
    ["provisional", "Provisional"],
    ["review", "Needs review"],
  ] as const;

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  }

  async function applyBulk() {
    const ids = selected.filter((id) => {
      const match = rows.find((item) => item.id === id);
      return match !== undefined && canCategorize(match);
    });
    if (ids.length === 0 || bulkCategory === "") {
      return;
    }
    await onCategorizeMany(ids, bulkCategory);
    setSelected([]);
    setBulkCategory("");
  }

  return (
    <div
      className={`tx-page${fresh ? " stage-enter" : ""}${selected.length > 0 ? " has-bulk" : ""}`}
    >
      <div className="tx-toolbar">
        <label className="sr-only" htmlFor="q">
          Search counterparties
        </label>
        <input
          className="field"
          id="q"
          value={query}
          placeholder="Search"
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
        {chips.map(([value, label]) => (
          <button
            key={label}
            className="chip"
            type="button"
            aria-pressed={(confirmation || "") === value}
            onClick={() => {
              onConfirmation(value);
            }}
          >
            {label}
          </button>
        ))}
        {accountId !== "" ? (
          <button
            className="chip"
            type="button"
            aria-pressed="true"
            onClick={() => {
              onAccount("");
            }}
          >
            {accounts.find((account) => account.id === accountId)?.name ??
              "Account"}{" "}
            ×
          </button>
        ) : null}
        {category !== "" ? (
          <button
            className="chip"
            type="button"
            aria-pressed="true"
            onClick={() => {
              onCategory("");
            }}
          >
            {category} ×
          </button>
        ) : null}
        <div className="add-filter">
          <button
            className="chip"
            type="button"
            aria-expanded={addOpen}
            onClick={() => {
              setAddOpen((open) => !open);
            }}
          >
            <PlusIcon /> Add filter
          </button>
          {addOpen ? (
            <div className="add-filter-menu" role="menu">
              <select
                className="select"
                aria-label="Financial Account"
                value={accountId}
                onChange={(event) => {
                  onAccount(event.target.value);
                  setAddOpen(false);
                }}
              >
                <option value="">All Financial Accounts</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}
                  </option>
                ))}
              </select>
              <select
                className="select"
                aria-label="Category"
                value={category}
                onChange={(event) => {
                  onCategory(event.target.value);
                  setAddOpen(false);
                }}
              >
                <option value="">All Categories</option>
                {categories.map((item) => (
                  <option key={item.id} value={item.name}>
                    {item.name}
                  </option>
                ))}
                <option value="Uncategorized">Uncategorized</option>
              </select>
            </div>
          ) : null}
        </div>
      </div>
      <div className="tx-summary" aria-label="Filtered totals">
        <span>
          <strong>{summary.count}</strong>{" "}
          {summary.count === 1 ? "transaction" : "transactions"}
        </span>
        <span>
          Total spent{" "}
          <strong className="amount">
            {formatUnsigned(centsToMoney(summary.spentCents, summary.currency))}
          </strong>
        </span>
        <span>
          Total income{" "}
          <strong className="amount">
            {formatUnsigned(
              centsToMoney(summary.incomeCents, summary.currency),
            )}
          </strong>
        </span>
        <span>
          Net{" "}
          <strong className="amount">
            {formatUnsigned(centsToMoney(summary.netCents, summary.currency))}
          </strong>
        </span>
      </div>
      <section className="card tx-list" id="txn-list">
        {groups.length === 0 ? (
          <p className="empty">No Transactions match these filters.</p>
        ) : (
          groups.map((group) => (
            <div key={group.date}>
              <div className="tx-group-head">
                <h2 className="group-label">{group.key}</h2>
                <span className="amount">
                  {formatUnsigned(
                    centsToMoney(groupSpentCents(group.rows), summary.currency),
                  )}
                </span>
              </div>
              {group.rows.map((transaction) => (
                <TransactionRow
                  key={transaction.id}
                  transaction={transaction}
                  compact={false}
                  selectable
                  selected={selectedId === transaction.id}
                  checked={selectedSet.has(transaction.id)}
                  onOpen={onOpen}
                  onToggle={toggle}
                />
              ))}
            </div>
          ))
        )}
        {hasMore ? (
          <div className="recent-head">
            <Button variant="ghost" disabled={loadingMore} onClick={onLoadMore}>
              {loadingMore ? "Loading…" : "Load older Transactions"}
            </Button>
          </div>
        ) : null}
      </section>
      {selected.length > 0 ? (
        <div className="bulk-bar" role="toolbar" aria-label="Bulk actions">
          <span className="muted">{selected.length} selected</span>
          <select
            className="select"
            aria-label="Bulk Category"
            value={bulkCategory}
            onChange={(event) => {
              setBulkCategory(event.target.value);
            }}
          >
            <option value="">Choose Category</option>
            {categories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            disabled={bulkCategory === "" || saving !== null}
            onClick={() => {
              void applyBulk();
            }}
          >
            {saving !== null ? "Saving…" : "Apply Category"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setSelected([]);
            }}
          >
            Clear selection
          </Button>
        </div>
      ) : null}
    </div>
  );
}
