import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Category, Transaction } from "../api";
import { TransactionsPage } from "./TransactionsPage";

const coffee: Transaction = {
  id: "00000000-0000-0000-0000-000000000010",
  version: 1,
  financial_account: {
    id: "00000000-0000-0000-0000-000000000011",
    name: "Synthetic Card",
  },
  counterparty: "Synthetic Coffee",
  posted_amount: { amount: "-12.34", currency: "SGD" },
  authorized_amount: null,
  effective_date: "2026-01-10",
  kind: "expense",
  category_splits: [
    {
      id: "00000000-0000-0000-0000-000000000012",
      name: "Uncategorized",
      amount: { amount: "12.34", currency: "SGD" },
    },
  ],
  reviews: [
    {
      id: "00000000-0000-0000-0000-000000000013",
      condition_code: "categorization_needed",
      severity: "attention",
      version: 1,
      allowed_decisions: ["categorize"],
    },
  ],
};

const categories: Category[] = [
  {
    id: "00000000-0000-0000-0000-000000000099",
    name: "Synthetic Food",
    parent_id: null,
    active: true,
  },
];

describe("TransactionsPage", () => {
  it("renders Copilot-like list chrome for the current filter", () => {
    const onCategorizeMany = vi.fn();
    render(
      <TransactionsPage
        transactions={[coffee]}
        categories={categories}
        accounts={[{ id: coffee.financial_account.id, name: "Synthetic Card" }]}
        confirmation=""
        category=""
        accountId=""
        selectedId={null}
        today={new Date("2026-01-10T00:00:00")}
        loadingMore={false}
        hasMore={false}
        saving={null}
        onConfirmation={() => undefined}
        onCategory={() => undefined}
        onAccount={() => undefined}
        onOpen={() => undefined}
        onLoadMore={() => undefined}
        onCategorizeMany={onCategorizeMany}
      />,
    );

    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByLabelText("Filtered totals")).toHaveTextContent(
      "1 transaction",
    );
    expect(screen.getByText("Uncategorized")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select Synthetic Coffee" }),
    );
    expect(screen.getByRole("toolbar", { name: "Bulk actions" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    expect(screen.getByLabelText("Financial Account")).toBeInTheDocument();
    expect(screen.getByLabelText("Category")).toBeInTheDocument();
  });
});
