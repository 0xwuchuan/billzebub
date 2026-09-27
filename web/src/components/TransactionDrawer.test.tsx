import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Transaction } from "../api";
import { TransactionDrawer } from "./TransactionDrawer";

const originalMatchMedia = window.matchMedia;

const transaction: Transaction = {
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
      name: "Groceries",
      amount: { amount: "12.34", currency: "SGD" },
    },
  ],
  reviews: [],
};

afterEach(() => {
  window.matchMedia = originalMatchMedia;
});

describe("TransactionDrawer", () => {
  it("renders an in-flow detail on desk, with a confirmation dot and no backdrop", () => {
    render(
      <TransactionDrawer
        transaction={transaction}
        categories={[]}
        draft=""
        saving={false}
        onDraft={() => undefined}
        onSave={() => undefined}
        onClose={() => undefined}
      />,
    );

    const detail = screen.getByRole("complementary", {
      name: "Synthetic Coffee",
    });
    expect(detail).toHaveClass("tx-detail");
    expect(detail.querySelector(".decision-hero")).not.toBeNull();
    expect(detail.querySelector(".cat-chip")).toHaveTextContent("Groceries");
    expect(detail.querySelector(".confirm-dot")).not.toBeNull();
    expect(detail).toHaveTextContent("Confirmed by Statement Claim");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.querySelector(".drawer-backdrop")).toBeNull();
  });

  it("keeps a dialog and backdrop on the phone overlay", () => {
    window.matchMedia = ((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    const onClose = vi.fn();
    render(
      <TransactionDrawer
        transaction={transaction}
        categories={[]}
        draft=""
        saving={false}
        onDraft={() => undefined}
        onSave={() => undefined}
        onClose={onClose}
      />,
    );

    expect(
      screen.getByRole("dialog", { name: "Synthetic Coffee" }),
    ).toBeInTheDocument();
    expect(document.querySelector(".tx-detail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close detail" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
