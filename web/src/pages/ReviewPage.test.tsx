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

  it("shows context Counterparty and amount in the pending queue when the list misses", () => {
    const orphan = {
      ...coffeeReview,
      context: {
        transaction_id: coffee.id,
        counterparty: "Synthetic Orphan Cafe",
        amount: "-18.50",
        currency: "SGD",
      },
    };
    renderPage({
      reviews: [orphan],
      transactions: [],
    });

    const queue = screen.getByRole("region", { name: "Pending Review queue" });
    const row = within(queue).getByRole("button", {
      name: /Synthetic Orphan Cafe/,
    });
    expect(row).toHaveTextContent("Synthetic Orphan Cafe");
    expect(row).toHaveTextContent("SGD 18.50");
    expect(row).not.toHaveTextContent("Category needed");
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
      expect(screen.queryByText("Review details")).not.toBeInTheDocument();
    } finally {
      window.matchMedia = original;
    }
  });

  it("renders Counterparty and amount from Review context when the Transaction list misses", () => {
    const orphan = {
      ...coffeeReview,
      context: {
        transaction_id: coffee.id,
        counterparty: "Synthetic Orphan Cafe",
        amount: "-18.50",
        currency: "SGD",
        account: "Synthetic Card",
        effective_date: "2026-01-10",
        version: 1,
      },
    };
    renderPage({
      reviews: [orphan],
      transactions: [],
    });

    const card = screen.getByRole("region", { name: "Review decision" });
    expect(
      within(card).getByRole("heading", { name: "Synthetic Orphan Cafe" }),
    ).toBeInTheDocument();
    expect(card.querySelector(".decision-amount")).toHaveTextContent(
      "SGD 18.50",
    );
    expect(within(card).getByText("Assign Category")).toBeInTheDocument();
    expect(
      within(card).queryByRole("heading", { name: "Category needed" }),
    ).not.toBeInTheDocument();
    expect(within(card).queryByText("Review details")).not.toBeInTheDocument();
    expect(
      within(card).queryByText("Transaction action required"),
    ).not.toBeInTheDocument();
    expect(within(card).queryByText("condition_code")).not.toBeInTheDocument();
  });

  it("never uses Category needed as the categorization heading", () => {
    renderPage({
      reviews: [coffeeReview],
      transactions: [],
    });

    expect(
      screen.getByRole("heading", { name: "Unknown Counterparty" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Category needed" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Assign Category")).toBeInTheDocument();
  });

  it("omits Review details chrome from categorization cards", () => {
    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
    });

    const card = screen.getByRole("region", { name: "Review decision" });
    expect(within(card).queryByText("Review details")).not.toBeInTheDocument();
    expect(within(card).queryByText(coffeeReview.id)).not.toBeInTheDocument();
    expect(within(card).queryByText("Claim evidence")).not.toBeInTheDocument();
    expect(within(card).queryByText("Raw source")).not.toBeInTheDocument();
    expect(
      within(card).queryByText("Amount in question"),
    ).not.toBeInTheDocument();
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
    expect(screen.getByRole("region", { name: "Review decision" })).toHaveClass(
      "is-empty",
    );
  });

  it("moves the queue with j, k, and arrow keys", () => {
    const onSelect = vi.fn();
    const { rerender } = renderPage({
      reviews: [coffeeReview, grocerReview],
      transactions: [coffee, grocer],
      onSelect,
    });

    fireEvent.keyDown(document.body, { key: "j" });
    fireEvent.keyDown(document.body, { key: "ArrowDown" });
    expect(onSelect).toHaveBeenCalledWith(grocerReview.id);

    rerender(
      pageElement({
        reviews: [coffeeReview, grocerReview],
        transactions: [coffee, grocer],
        selectedId: grocerReview.id,
        onSelect,
      }),
    );
    fireEvent.keyDown(document.body, { key: "k" });
    fireEvent.keyDown(document.body, { key: "ArrowUp" });
    expect(onSelect).toHaveBeenCalledWith(coffeeReview.id);
  });

  it("assigns with Enter and advances to the next review", () => {
    const onAssign = vi.fn();
    const onSelect = vi.fn();
    renderPage({
      reviews: [coffeeReview, grocerReview],
      transactions: [coffee, grocer],
      drafts: { [coffee.id]: categories[0]?.id ?? "" },
      onAssign,
      onSelect,
    });

    fireEvent.keyDown(document.body, { key: "Enter" });

    expect(onAssign).toHaveBeenCalledWith(coffee);
    expect(onSelect).toHaveBeenCalledWith(grocerReview.id);
  });

  it("confirms the primary decision with Enter and advances", () => {
    const onDecide = vi.fn();
    const onSelect = vi.fn();
    const match = {
      ...coffeeReview,
      condition_code: "reconciliation_ambiguous",
      allowed_decisions: ["confirm_match", "keep_separate"],
    };
    renderPage({
      reviews: [match, grocerReview],
      transactions: [coffee, grocer],
      onDecide,
      onSelect,
    });

    fireEvent.keyDown(document.body, { key: "Enter" });

    expect(onDecide).toHaveBeenCalledWith(match, "confirm_match");
    expect(onSelect).toHaveBeenCalledWith(grocerReview.id);
  });

  it("opens category search from slash or type-ahead and closes it with Esc", () => {
    const onDraft = vi.fn();
    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
      categories: [
        categories[0]!,
        {
          id: "00000000-0000-0000-0000-000000000098",
          name: "Transit",
          parent_id: null,
          active: true,
        },
      ],
      onDraft,
    });

    fireEvent.keyDown(document.body, { key: "/" });
    const search = screen.getByRole("combobox", {
      name: "Category for Synthetic Coffee",
    });
    expect(search).toHaveFocus();
    expect(search).toHaveValue("");

    fireEvent.keyDown(search, { key: "Escape" });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText("Choose Category")).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "f" });
    const typed = screen.getByRole("combobox");
    expect(typed).toHaveFocus();
    expect(typed).toHaveValue("f");
    expect(
      screen.getByRole("option", { name: "Synthetic Food" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Transit" }),
    ).not.toBeInTheDocument();

    fireEvent.keyDown(typed, { key: "Enter" });
    expect(onDraft).toHaveBeenCalledWith(coffee.id, categories[0]?.id);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("keeps j and k for the queue until category search is focused", () => {
    const onSelect = vi.fn();
    renderPage({
      reviews: [coffeeReview, grocerReview],
      transactions: [coffee, grocer],
      onSelect,
    });

    const queue = screen.getByRole("region", { name: "Pending Review queue" });
    const row = within(queue).getByRole("button", { name: /Synthetic Coffee/ });
    row.focus();
    fireEvent.keyDown(row, { key: "f" });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "/" });
    const search = screen.getByRole("combobox");
    fireEvent.keyDown(search, { key: "j" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("lists the review keyboard shortcuts on the decision card", () => {
    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
    });

    const shortcuts = screen.getByRole("list", { name: "Keyboard shortcuts" });
    expect(shortcuts).toHaveTextContent("Enter");
    expect(shortcuts).toHaveTextContent("open category search");
    expect(shortcuts).toHaveTextContent("move queue");
    expect(shortcuts).toHaveTextContent("type-ahead opens category search");
    expect(shortcuts).toHaveTextContent("closes search");
  });

  it("does not stretch the empty decision card, and keeps a filled card compact-capable", () => {
    const { unmount } = renderPage({ reviews: [], transactions: [] });
    expect(screen.getByRole("region", { name: "Review decision" })).toHaveClass(
      "is-empty",
    );
    unmount();

    renderPage({
      reviews: [coffeeReview],
      transactions: [coffee],
    });
    expect(
      screen.getByRole("region", { name: "Review decision" }),
    ).not.toHaveClass("is-empty");
    expect(
      screen.getByRole("heading", { name: "Synthetic Coffee" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Assign Category" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Review details")).not.toBeInTheDocument();
  });
});

function renderPage(props: PageProps) {
  return render(pageElement(props));
}

function pageElement({
  reviews,
  transactions,
  drafts = {},
  categories: categoryList = categories,
  selectedId = "",
  onAssign = () => undefined,
  onSelect = () => undefined,
  onDraft = () => undefined,
  onDecide = () => undefined,
}: PageProps) {
  return (
    <ReviewPage
      reviews={reviews}
      transactions={transactions}
      imports={[]}
      categories={categoryList}
      filter=""
      selectedId={selectedId}
      drafts={drafts}
      saving={null}
      today={new Date("2026-01-19T00:00:00+00:00")}
      onFilter={() => undefined}
      onSelect={onSelect}
      onDraft={onDraft}
      onAssign={onAssign}
      onDecide={onDecide}
      onOpenTransaction={() => undefined}
      onOpenImport={() => undefined}
      onOpenSettings={() => undefined}
    />
  );
}

type PageProps = {
  reviews: Review[];
  transactions: Transaction[];
  drafts?: Record<string, string>;
  categories?: Category[];
  selectedId?: string;
  onAssign?: (transaction: Transaction) => void;
  onSelect?: (id: string) => void;
  onDraft?: (transactionId: string, categoryId: string) => void;
  onDecide?: (review: Review, choice: string) => void;
};
