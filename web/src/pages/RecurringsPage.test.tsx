import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Category, RecurringSeries } from "../api";
import { RecurringsPage } from "./RecurringsPage";

const today = new Date(2026, 8, 15);

const categories: Category[] = [
  {
    id: "cat-dining",
    name: "Dining",
    parent_id: null,
    active: true,
  },
];

function series(overrides: Partial<RecurringSeries> = {}): RecurringSeries {
  return {
    id: "series-1",
    counterparty: "Synthetic Stream",
    amount: { amount: "16.98", currency: "SGD" },
    amount_min: null,
    amount_max: null,
    cadence: "monthly",
    interval_days: null,
    next_expected_date: "2026-09-18",
    category_id: "cat-dining",
    primary_account_id: "acct-1",
    status: "proposed",
    source: "detected",
    confidence: "0.91",
    last_matched_tx_id: null,
    last_amount: { amount: "16.98", currency: "SGD" },
    linked_count: 3,
    missed: false,
    notes: null,
    cluster_key: "stream",
    ...overrides,
  };
}

function renderPage(
  overrides: Partial<Parameters<typeof RecurringsPage>[0]> = {},
) {
  const props = {
    proposed: [] as RecurringSeries[],
    active: [] as RecurringSeries[],
    paused: [] as RecurringSeries[],
    categories,
    accounts: [{ id: "acct-1", name: "Citi PremierMiles", currency: "SGD" }],
    tab: "" as const,
    loading: false,
    saving: null,
    error: null,
    today,
    onTab: vi.fn(),
    onConfirm: vi.fn(async () => true),
    onDismiss: vi.fn(async () => true),
    onUpdate: vi.fn(async () => true),
    onCreate: vi.fn(async () => true),
    onNotice: vi.fn(),
    ...overrides,
  };
  render(<RecurringsPage {...props} />);
  return props;
}

describe("Recurrings page", () => {
  it("defaults to Active when nothing is proposed", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Active" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByText(/No active series yet. Add one, or wait for detections/),
    ).toBeInTheDocument();
  });

  it("keeps an empty Proposed inbox calm", () => {
    const props = renderPage({ tab: "proposed" });
    const empty = screen.getByText(/No proposals waiting/);
    fireEvent.click(within(empty).getByRole("button", { name: "Active" }));
    expect(props.onTab).toHaveBeenCalledWith("active");
  });

  it("lists proposed rows and confirms from the edit sheet", async () => {
    const props = renderPage({
      proposed: [series()],
    });
    expect(screen.getByRole("button", { name: "Proposed" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const row = screen.getByRole("listitem");
    expect(row).toHaveTextContent("Synthetic Stream");
    expect(row).toHaveTextContent("−SGD 16.98");
    expect(row).toHaveTextContent("Monthly");
    expect(row).toHaveTextContent("High");
    expect(row.querySelector(".cat-chip")).toHaveTextContent("Dining");
    expect(row.querySelector(".badge")).toBeNull();

    fireEvent.click(within(row).getByRole("button", { name: "Confirm" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Synthetic Stream");
    expect(within(dialog).getByLabelText("Cadence")).toHaveValue("monthly");
    expect(within(dialog).getByLabelText("Next expected")).toHaveValue(
      "2026-09-18",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(props.onConfirm).toHaveBeenCalledWith("series-1", {
      cadence: "monthly",
      next_expected_date: "2026-09-18",
      category_id: "cat-dining",
    });
  });

  it("dismisses a proposal in one click", () => {
    const props = renderPage({ proposed: [series()] });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(props.onDismiss).toHaveBeenCalledWith("series-1");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms the focused proposal with Enter", () => {
    const props = renderPage({ proposed: [series()] });
    const row = screen.getByRole("listitem");
    row.focus();
    fireEvent.keyDown(row, { key: "Enter" });
    expect(props.onConfirm).toHaveBeenCalledWith("series-1", {
      status: "active",
    });
  });

  it("lists active series with pause, edit, and end", async () => {
    const props = renderPage({
      tab: "active",
      active: [
        series({
          id: "active-1",
          status: "active",
          next_expected_date: "2026-09-18",
          missed: true,
        }),
        series({
          id: "active-2",
          counterparty: "Synthetic Rent",
          status: "active",
          next_expected_date: "2026-10-02",
          category_id: null,
          missed: false,
        }),
      ],
      paused: [
        series({
          id: "paused-1",
          counterparty: "Synthetic Gym",
          status: "paused",
        }),
      ],
    });
    expect(screen.getByText("Due this week")).toBeInTheDocument();
    expect(screen.getByText("Later")).toBeInTheDocument();
    const missed = screen.getByText("Synthetic Stream").closest("article");
    expect(missed).toHaveTextContent("Missed");
    expect(missed).toHaveTextContent("Citi PremierMiles");
    expect(missed?.querySelector(".recurring-miss")).not.toBeNull();

    fireEvent.click(
      within(missed as HTMLElement).getByRole("button", {
        name: "Actions for Synthetic Stream",
      }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Pause" }));
    expect(props.onUpdate).toHaveBeenCalledWith("active-1", {
      status: "paused",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Actions for Synthetic Rent" }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "End" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Ends matching future txs.");
    fireEvent.click(within(dialog).getByRole("button", { name: "End" }));
    expect(props.onUpdate).toHaveBeenCalledWith("active-2", {
      status: "ended",
    });

    expect(screen.getByText("1 paused")).toBeInTheDocument();
  });

  it("creates a manual series from Add", async () => {
    const props = renderPage({ tab: "active" });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Counterparty"), {
      target: { value: "Synthetic Rent" },
    });
    fireEvent.change(within(dialog).getByLabelText("Amount"), {
      target: { value: "2400" },
    });
    fireEvent.change(within(dialog).getByLabelText("Next expected"), {
      target: { value: "2026-10-01" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Dining" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(props.onCreate).toHaveBeenCalledWith({
      counterparty: "Synthetic Rent",
      amount: "2400",
      currency: "SGD",
      cadence: "monthly",
      next_expected_date: "2026-10-01",
      category_id: "cat-dining",
    });
  });
});
