import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Transaction } from "../api";
import { OverviewPage } from "./OverviewPage";

const today = new Date(2026, 8, 15);

function expense(
  id: string,
  counterparty: string,
  cents: number,
  category: string,
  day: number,
  provisional = false,
): Transaction {
  const amount = (cents / 100).toFixed(2);
  return {
    id,
    version: 1,
    financial_account: {
      id: "00000000-0000-0000-0000-000000000011",
      name: "Synthetic Card",
    },
    counterparty,
    posted_amount: {
      amount: provisional ? "0.00" : `-${amount}`,
      currency: "SGD",
    },
    authorized_amount: provisional
      ? { amount: `-${amount}`, currency: "SGD" }
      : null,
    effective_date: `2026-09-${String(day).padStart(2, "0")}`,
    kind: "expense",
    category_splits: [
      {
        id: `${id}-split`,
        name: category,
        amount: { amount, currency: "SGD" },
      },
    ],
    reviews: [],
  };
}

const transactions = [
  expense("tx-1", "Synthetic Grocer", 50000, "Groceries", 14),
  expense("tx-2", "Synthetic Bistro", 40000, "Dining", 13),
  expense("tx-3", "Synthetic Rail", 30000, "Transport", 12),
  expense("tx-4", "Synthetic Power", 20000, "Utilities", 11),
  expense("tx-5", "Synthetic Clinic", 10000, "Health", 10),
  expense("tx-6", "Synthetic Shop", 5000, "Shopping", 9),
  expense("tx-7", "Synthetic Wallet Cafe", 800, "Dining", 15, true),
];

function renderOverview(reviewCount = 3, blockingCount = 1) {
  const onOpenTransaction = vi.fn();
  const onFilterConfirmed = vi.fn();
  const onFilterProvisional = vi.fn();
  const onOpenReview = vi.fn();
  const onOpenTransactions = vi.fn();
  const onFilterCategory = vi.fn();
  render(
    <OverviewPage
      transactions={transactions}
      reviewCount={reviewCount}
      blockingCount={blockingCount}
      today={today}
      onOpenTransaction={onOpenTransaction}
      onFilterConfirmed={onFilterConfirmed}
      onFilterProvisional={onFilterProvisional}
      onOpenReview={onOpenReview}
      onOpenTransactions={onOpenTransactions}
      onFilterCategory={onFilterCategory}
    />,
  );
  return {
    onOpenTransaction,
    onFilterConfirmed,
    onFilterProvisional,
    onOpenReview,
    onOpenTransactions,
    onFilterCategory,
  };
}

describe("Overview bento", () => {
  it("leads with the month figure, a quiet attention line, and five categories", () => {
    const actions = renderOverview();

    expect(
      screen.getByRole("heading", { name: "This month" }),
    ).toBeInTheDocument();
    expect(screen.getByText("SGD 1,558.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Confirmed/ })).toHaveTextContent(
      "SGD 1,550.00",
    );
    expect(
      screen.getByRole("button", { name: /^Provisional/ }),
    ).toHaveTextContent("SGD 8.00");

    const attention = document.querySelector(".bento-attention");
    expect(attention).toHaveClass("has-queue");
    expect(attention).toHaveTextContent("3");
    expect(attention).toHaveTextContent("1 blocking · 2 attention");
    expect(attention).toHaveTextContent("Review →");

    const list = document.querySelector(".cat-list");
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll(".cat-chip")).toHaveLength(5);
    expect(list).toHaveTextContent("1 more");
    expect(list).not.toHaveTextContent("Shopping");
    expect(list?.querySelector(".cat-share")).toBeNull();
    expect(list?.querySelector(".cat-chip")).not.toBeNull();

    const recent = document.querySelectorAll(".bento-recent .tx-row");
    expect(recent).toHaveLength(5);
    expect(recent[0]).toHaveClass("is-compact");
    expect(
      recent[0]?.querySelector(".tx-amount-side .provisional-dot"),
    ).not.toBeNull();
    expect(document.querySelector(".provisional-badge")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^Confirmed/ }));
    fireEvent.click(screen.getByRole("button", { name: /Review →/ }));
    fireEvent.click(screen.getByRole("button", { name: "All transactions →" }));
    fireEvent.click(screen.getByRole("button", { name: /Synthetic Grocer/ }));
    fireEvent.click(
      within(list as HTMLElement).getByRole("button", { name: /Groceries/ }),
    );

    expect(actions.onFilterConfirmed).toHaveBeenCalledOnce();
    expect(actions.onOpenReview).toHaveBeenCalledOnce();
    expect(actions.onOpenTransactions).toHaveBeenCalledOnce();
    expect(actions.onOpenTransaction).toHaveBeenCalledWith("tx-1");
    expect(actions.onFilterCategory).toHaveBeenCalledWith("Groceries");
  });

  it("keeps a clear Attention queue calm", () => {
    renderOverview(0, 0);
    const attention = document.querySelector(".bento-attention");
    expect(attention).not.toHaveClass("has-queue");
    expect(attention).toHaveTextContent("Queue is clear");
  });
});
