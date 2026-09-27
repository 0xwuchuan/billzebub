import { useEffect, useState, type ReactNode } from "react";

import type { Category, Transaction } from "../api";
import { TxRow } from "../components/TxRow";
import { Button } from "../components/ui/Button";
import { PlusIcon } from "../components/icons";
import { useEntrance } from "../hooks/useEntrance";
import { useOverlayMedia } from "../hooks/useOverlayMedia";
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
  detail = null,
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
  detail?: ReactNode;
}) {
  const fresh = useEntrance("transactions");
  const overlay = useOverlayMedia();
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

  useEffect(() => {
    if (selectedId === null || overlay) {
      return;
    }
    const openId = selectedId;
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) {
        return;
      }
      const delta =
        event.key === "j" || event.key === "ArrowDown"
          ? 1
          : event.key === "k" || event.key === "ArrowUp"
            ? -1
            : 0;
      if (delta === 0 || isEditableTarget(event.target)) {
        return;
      }
      const next = neighborRow(rows, openId, delta);
      if (next === null) {
        return;
      }
      event.preventDefault();
      if (next.id !== openId) {
        onOpen(next.id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onOpen, overlay, rows, selectedId]);

  useEffect(() => {
    if (selectedId === null || overlay) {
      return;
    }
    const row = document.querySelector<HTMLElement>(".tx-row.is-selected");
    if (row !== null && typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ block: "nearest" });
    }
  }, [overlay, selectedId]);

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
      className={`tx-page${fresh ? " stage-enter" : ""}${selected.length > 0 ? " has-bulk" : ""}${detail != null ? " has-detail" : ""}`}
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
          <strong className="amount">{summary.count}</strong>{" "}
          {summary.count === 1 ? "transaction" : "transactions"}
        </span>
        <span className="tx-summary-sep" aria-hidden="true">
          ·
        </span>
        <span>
          Total spent{" "}
          <strong className="amount">
            {formatUnsigned(centsToMoney(summary.spentCents, summary.currency))}
          </strong>
        </span>
        <span className="tx-summary-sep" aria-hidden="true">
          ·
        </span>
        <span>
          Total income{" "}
          <strong className="amount">
            {formatUnsigned(
              centsToMoney(summary.incomeCents, summary.currency),
            )}
          </strong>
        </span>
        <span className="tx-summary-sep" aria-hidden="true">
          ·
        </span>
        <span>
          Net{" "}
          <strong className="amount">
            {formatUnsigned(centsToMoney(summary.netCents, summary.currency))}
          </strong>
        </span>
      </div>
      <div className="tx-split">
        <div className="tx-list-col">
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
                        centsToMoney(
                          groupSpentCents(group.rows),
                          summary.currency,
                        ),
                      )}
                    </span>
                  </div>
                  {group.rows.map((transaction) => (
                    <TxRow
                      key={transaction.id}
                      transaction={transaction}
                      selectable
                      selected={selectedId === transaction.id}
                      checked={selectedSet.has(transaction.id)}
                      provisionalMark="dot"
                      onOpen={onOpen}
                      onToggle={toggle}
                    />
                  ))}
                </div>
              ))
            )}
            {hasMore ? (
              <div className="recent-head">
                <Button
                  variant="ghost"
                  disabled={loadingMore}
                  onClick={onLoadMore}
                >
                  {loadingMore ? "Loading…" : "Load older Transactions"}
                </Button>
              </div>
            ) : null}
          </section>
          {selected.length > 0 ? (
            <BulkBar
              count={selected.length}
              categories={categories}
              bulkCategory={bulkCategory}
              saving={saving !== null}
              onClear={() => {
                setSelected([]);
              }}
              onCategory={setBulkCategory}
              onApply={() => {
                void applyBulk();
              }}
            />
          ) : null}
        </div>
        {detail}
      </div>
    </div>
  );
}

function BulkBar({
  count,
  categories,
  bulkCategory,
  saving,
  onClear,
  onCategory,
  onApply,
}: {
  count: number;
  categories: Category[];
  bulkCategory: string;
  saving: boolean;
  onClear: () => void;
  onCategory: (categoryId: string) => void;
  onApply: () => void;
}) {
  return (
    <div className="bulk-bar" role="toolbar" aria-label="Bulk actions">
      <span className="bulk-count">
        <strong className="amount">{count}</strong> selected
      </span>
      <Button variant="ghost" aria-label="Clear selection" onClick={onClear}>
        Clear
      </Button>
      <select
        className="select"
        aria-label="Bulk Category"
        value={bulkCategory}
        onChange={(event) => {
          onCategory(event.target.value);
        }}
      >
        <option value="">Category</option>
        {categories.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      <Button
        variant="primary"
        disabled={bulkCategory === "" || saving}
        onClick={onApply}
      >
        {saving ? "Saving…" : "Apply Category"}
      </Button>
    </div>
  );
}

function neighborRow(
  rows: Transaction[],
  selectedId: string,
  delta: 1 | -1,
): Transaction | null {
  if (rows.length === 0) {
    return null;
  }
  const index = rows.findIndex((row) => row.id === selectedId);
  if (index === -1) {
    return delta > 0 ? (rows[0] ?? null) : (rows[rows.length - 1] ?? null);
  }
  return rows[index + delta] ?? null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "SELECT" ||
    tag === "TEXTAREA" ||
    target.isContentEditable
  );
}
