import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Category, Review, Transaction } from "../api";
import { ReviewPage } from "./ReviewPage";

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
  category_splits: [],
  reviews: [],
};

const grocer: Transaction = {
  ...coffee,
  id: "00000000-0000-0000-0000-000000000020",
  counterparty: "Synthetic Grocer",
  posted_amount: { amount: "-8.00", currency: "SGD" },
  effective_date: "2026-01-11",
};

const coffeeReview: Review = {
  id: "00000000-0000-0000-0000-000000000013",
  subject_type: "transaction",
  subject_id: coffee.id,
  condition_code: "categorization_needed",
  severity: "attention",
  status: "pending",
  version: 1,
  allowed_decisions: ["categorize"],
  context: {},
  created_at: "2026-01-10T00:00:00+00:00",
  updated_at: "2026-01-10T00:00:00+00:00",
};

const grocerReview: Review = {
  ...coffeeReview,
  id: "00000000-0000-0000-0000-000000000021",
  subject_id: grocer.id,
  created_at: "2026-01-11T00:00:00+00:00",
  updated_at: "2026-01-11T00:00:00+00:00",
};

const categories: Category[] = [
  {
    id: "00000000-0000-0000-0000-000000000099",
    name: "Synthetic Food",
    parent_id: null,
    active: true,
  },
];

describe("ReviewPage", () => {
  it("leads the decision card with Counterparty and amount, not the condition title", () => {
    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
    });

    const card = screen.getByRole("region", { name: "Review decision" });
    expect(
      within(card).getByRole("heading", { name: "Synthetic Coffee" }),
    ).toBeInTheDocument();
    expect(card.querySelector(".decision-amount")).toHaveTextContent(
      "SGD 12.34",
    );
    expect(within(card).getByText("Category needed")).toBeInTheDocument();
    expect(
      within(card).queryByRole("heading", { name: "Category needed" }),
    ).not.toBeInTheDocument();
    expect(within(card).getByText("Assign Category")).toBeInTheDocument();
  });

  it("shows Counterparty, amount, and age in the pending queue", () => {
    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
    });

    const queue = screen.getByRole("region", { name: "Pending Review queue" });
    const row = within(queue).getByRole("button", {
      name: /Synthetic Coffee/,
    });
    expect(row).toHaveTextContent("Synthetic Coffee");
    expect(row).toHaveTextContent("SGD 12.34");
    expect(row).toHaveTextContent("opened");
    expect(row).not.toHaveTextContent("Category needed");
  });

  it("assigns a Category and advances to the next pending card", () => {
    const onAssign = vi.fn();
    const onSelect = vi.fn();
    renderPage({
      reviews: [coffeeReview, grocerReview],
      transactions: [coffee, grocer],
      drafts: { [coffee.id]: categories[0]?.id ?? "" },
      onAssign,
      onSelect,
    });

    fireEvent.click(screen.getByRole("button", { name: "Assign Category" }));

    expect(onAssign).toHaveBeenCalledWith(coffee);
    expect(onSelect).toHaveBeenCalledWith(grocerReview.id);
    expect(
      screen.getByRole("heading", { name: "Synthetic Grocer" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Synthetic Coffee" }),
    ).not.toBeInTheDocument();
  });

  it("hides the pending queue in the card-only mobile flow", () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    try {
      renderPage({
        reviews: [coffeeReview],
        transactions: [coffee],
      });
      expect(
        screen.queryByRole("region", { name: "Pending Review queue" }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Synthetic Coffee" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Assign Category" }),
      ).toBeInTheDocument();
    } finally {
      window.matchMedia = original;
    }
  });

  it("shows the empty state after the last categorization assign", () => {
    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
      drafts: { [coffee.id]: categories[0]?.id ?? "" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Assign Category" }));

    expect(
      screen.getByText(
        "Nothing to decide. Pick another filter or come back after the next Extraction.",
      ),
    ).toBeInTheDocument();
  });
});

function renderPage({
  reviews,
  transactions,
  drafts = {},
  onAssign = () => undefined,
  onSelect = () => undefined,
}: {
  reviews: Review[];
  transactions: Transaction[];
  drafts?: Record<string, string>;
  onAssign?: (transaction: Transaction) => void;
  onSelect?: (id: string) => void;
}) {
  return render(
    <ReviewPage
      reviews={reviews}
      transactions={transactions}
      imports={[]}
      categories={categories}
      filter=""
      selectedId=""
      drafts={drafts}
      saving={null}
      today={new Date("2026-01-19T00:00:00+00:00")}
      onFilter={() => undefined}
      onSelect={onSelect}
      onDraft={() => undefined}
      onAssign={onAssign}
      onDecide={() => undefined}
      onOpenTransaction={() => undefined}
      onOpenImport={() => undefined}
      onOpenSettings={() => undefined}
    />,
  );
}
