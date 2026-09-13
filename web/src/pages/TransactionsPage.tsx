import { useState } from "react";

import type { Category, Transaction } from "../api";
import { TransactionRow } from "../components/TransactionRow";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import type { ConfirmationFilter } from "../lib/route";
import {
  filterTransactions,
  groupTransactions,
  sortTransactions,
} from "../lib/workspace";

export function TransactionsPage({
  transactions,
  categories,
  accounts,
  confirmation,
  category,
  today,
  loadingMore,
  hasMore,
  onConfirmation,
  onCategory,
  onOpen,
  onLoadMore,
}: {
  transactions: Transaction[];
  categories: Category[];
  accounts: Array<{ id: string; name: string }>;
  confirmation: ConfirmationFilter;
  category: string;
  today: Date;
  loadingMore: boolean;
  hasMore: boolean;
  onConfirmation: (value: ConfirmationFilter) => void;
  onCategory: (value: string) => void;
  onOpen: (id: string) => void;
  onLoadMore: () => void;
}) {
  const fresh = useEntrance("transactions");
  const [query, setQuery] = useState("");
  const [accountId, setAccountId] = useState("");
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
  const chips = [
    ["", "All"],
    ["confirmed", "Confirmed"],
    ["provisional", "Provisional"],
    ["review", "Needs review"],
  ] as const;
  return (
    <>
      <div className={`filters${fresh ? " stage-enter" : ""}`}>
        <label className="sr-only" htmlFor="q">
          Search counterparties
        </label>
        <input
          className="field"
          id="q"
          value={query}
          placeholder="Search Counterparty or raw text"
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
        <select
          className="select"
          aria-label="Financial Account"
          value={accountId}
          onChange={(event) => {
            setAccountId(event.target.value);
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
      </div>
      <section className="card recent" id="txn-list">
        {groups.length === 0 ? (
          <p className="empty">No Transactions match these filters.</p>
        ) : (
          groups.map((group) => (
            <div key={group.key}>
              <h2 className="group-label">{group.key}</h2>
              {group.rows.map((transaction) => (
                <TransactionRow
                  key={transaction.id}
                  transaction={transaction}
                  compact={false}
                  onOpen={onOpen}
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
    </>
  );
}
