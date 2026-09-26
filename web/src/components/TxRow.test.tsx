import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Transaction } from "../api";
import { TxRow } from "./TxRow";

function transaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
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
        name: "Dining",
        amount: { amount: "12.34", currency: "SGD" },
      },
    ],
    reviews: [],
    ...overrides,
  };
}

describe("TxRow", () => {
  it("shows the category chip and Provisional together for a claim-only row", () => {
    const provisional = transaction({
      counterparty: "Synthetic Wallet Merchant",
      posted_amount: { amount: "0", currency: "SGD" },
      authorized_amount: { amount: "-12.34", currency: "SGD" },
      category_splits: [
        {
          id: "00000000-0000-0000-0000-000000000013",
          name: "Dining",
          amount: { amount: "12.34", currency: "SGD" },
        },
      ],
    });
    render(<TxRow transaction={provisional} onOpen={() => undefined} />);

    const row = screen.getByRole("button", {
      name: /Synthetic Wallet Merchant/,
    });
    expect(within(row).getByText("Dining")).toBeInTheDocument();
    expect(within(row).getByText("Provisional")).toBeInTheDocument();
    expect(row.querySelector(".cat-chip")).not.toBeNull();
    expect(row.querySelector(".provisional-badge")).not.toBeNull();
    expect(row).not.toHaveTextContent(provisional.id);
    expect(
      within(row).getByText("10 Jan · Synthetic Card"),
    ).toBeInTheDocument();
  });

  it("marks a provisional row with an amount-side dot instead of a badge", () => {
    const provisional = transaction({
      counterparty: "Synthetic Wallet Merchant",
      posted_amount: { amount: "0", currency: "SGD" },
      authorized_amount: { amount: "-12.34", currency: "SGD" },
    });
    render(
      <TxRow
        transaction={provisional}
        provisionalMark="dot"
        onOpen={() => undefined}
      />,
    );

    const row = screen.getByRole("button", {
      name: /Synthetic Wallet Merchant/,
    });
    expect(row.querySelector(".provisional-badge")).toBeNull();
    expect(row.querySelector(".cat-chip")).not.toBeNull();
    const dot = row.querySelector(".tx-amount-side .provisional-dot");
    expect(dot).not.toBeNull();
    expect(dot).toHaveAttribute("title", "Provisional");
    expect(row.querySelector(".tx-row-status .provisional-dot")).toBeNull();
  });

  it("shows only the category chip when the transaction is confirmed", () => {
    render(<TxRow transaction={transaction()} onOpen={() => undefined} />);

    const row = screen.getByRole("button", { name: /Synthetic Coffee/ });
    expect(within(row).getByText("Dining")).toBeInTheDocument();
    expect(within(row).queryByText("Provisional")).not.toBeInTheDocument();
    expect(row.querySelector(".provisional-badge")).toBeNull();
  });

  it("mutes an uncategorized chip", () => {
    render(
      <TxRow
        transaction={transaction({ category_splits: [] })}
        onOpen={() => undefined}
      />,
    );

    const chip = document.querySelector(".cat-chip");
    expect(chip).not.toBeNull();
    expect(chip?.classList.contains("is-muted")).toBe(true);
    expect(chip).toHaveTextContent("Uncategorized");
  });
});
