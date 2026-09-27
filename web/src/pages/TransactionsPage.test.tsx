import { fireEvent, render, screen, within } from "@testing-library/react";
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
    expect(document.querySelector(".tx-row-trailing")).not.toBeNull();
    expect(document.querySelector(".tx-page.has-bulk")).toBeNull();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select Synthetic Coffee" }),
    );
    const bulk = screen.getByRole("toolbar", { name: "Bulk actions" });
    expect(bulk).toBeVisible();
    expect(
      within(bulk).getByRole("button", { name: "Clear selection" }),
    ).toBeVisible();
    expect(
      within(bulk).getByRole("button", { name: "Apply Category" }),
    ).toBeVisible();
    expect(within(bulk).getByLabelText("Bulk Category")).toBeVisible();
    expect(document.querySelector(".tx-page.has-bulk")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    expect(screen.getByLabelText("Financial Account")).toBeInTheDocument();
    expect(screen.getByLabelText("Category")).toBeInTheDocument();
  });

  it("moves the open detail among visible rows with j and k, except in fields", () => {
    const onOpen = vi.fn();
    const tea: Transaction = {
      ...coffee,
      id: "00000000-0000-0000-0000-000000000030",
      counterparty: "Synthetic Tea",
      effective_date: "2026-01-09",
    };
    const { rerender } = render(
      <TransactionsPage
        transactions={[coffee, tea]}
        categories={categories}
        accounts={[{ id: coffee.financial_account.id, name: "Synthetic Card" }]}
        confirmation=""
        category=""
        accountId=""
        selectedId={coffee.id}
        today={new Date("2026-01-10T00:00:00")}
        loadingMore={false}
        hasMore={false}
        saving={null}
        onConfirmation={() => undefined}
        onCategory={() => undefined}
        onAccount={() => undefined}
        onOpen={onOpen}
        onLoadMore={() => undefined}
        onCategorizeMany={() => Promise.resolve()}
        detail={<p>Detail</p>}
      />,
    );

    expect(document.querySelector(".tx-page.has-detail")).not.toBeNull();
    fireEvent.keyDown(window, { key: "j" });
    expect(onOpen).toHaveBeenCalledWith(tea.id);

    rerender(
      <TransactionsPage
        transactions={[coffee, tea]}
        categories={categories}
        accounts={[{ id: coffee.financial_account.id, name: "Synthetic Card" }]}
        confirmation=""
        category=""
        accountId=""
        selectedId={tea.id}
        today={new Date("2026-01-10T00:00:00")}
        loadingMore={false}
        hasMore={false}
        saving={null}
        onConfirmation={() => undefined}
        onCategory={() => undefined}
        onAccount={() => undefined}
        onOpen={onOpen}
        onLoadMore={() => undefined}
        onCategorizeMany={() => Promise.resolve()}
        detail={<p>Detail</p>}
      />,
    );
    onOpen.mockClear();
    fireEvent.keyDown(window, { key: "k" });
    expect(onOpen).toHaveBeenCalledWith(coffee.id);

    onOpen.mockClear();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select Synthetic Tea" }),
    );
    const bulkCategory = screen.getByLabelText("Bulk Category");
    bulkCategory.focus();
    fireEvent.keyDown(bulkCategory, { key: "k" });
    expect(onOpen).not.toHaveBeenCalled();

    const search = screen.getByPlaceholderText("Search");
    search.focus();
    fireEvent.keyDown(search, { key: "j" });
    expect(onOpen).not.toHaveBeenCalled();

    fireEvent.change(search, { target: { value: "Coffee" } });
    search.blur();
    fireEvent.keyDown(window, { key: "j" });
    expect(onOpen).toHaveBeenCalledWith(coffee.id);
  });

  it("marks provisional rows with an amount-side dot and no badge", () => {
    const provisional: Transaction = {
      ...coffee,
      id: "00000000-0000-0000-0000-000000000020",
      counterparty: "Synthetic Wallet Merchant",
      posted_amount: { amount: "0", currency: "SGD" },
      authorized_amount: { amount: "-12.34", currency: "SGD" },
      reviews: [],
    };
    render(
      <TransactionsPage
        transactions={[provisional]}
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
        onCategorizeMany={() => Promise.resolve()}
      />,
    );

    const row = screen.getByRole("button", {
      name: /Synthetic Wallet Merchant/,
    });
    expect(row.querySelector(".cat-chip")).not.toBeNull();
    expect(row.querySelector(".provisional-badge")).toBeNull();
    expect(
      row.querySelector(".tx-amount-side .provisional-dot"),
    ).not.toBeNull();
    expect(
      screen.queryByText("Provisional", { selector: ".provisional-badge" }),
    ).toBeNull();
  });
});
