import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { SETUP_STORAGE_KEY } from "./lib/setup";
import { formatMoney } from "./lib/money";
import { hashFor, parseHash } from "./lib/route";
import {
  defaultSetupState,
  firstBlockedStep,
  reduceSetup,
  stepValid,
  type SetupState,
} from "./lib/setup";

const transaction = {
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
      severity: "attention" as const,
      version: 1,
      allowed_decisions: ["categorize"],
    },
  ],
};

const pendingReview = {
  id: "00000000-0000-0000-0000-000000000013",
  subject_type: "transaction",
  subject_id: transaction.id,
  condition_code: "categorization_needed",
  severity: "attention",
  status: "pending",
  version: 1,
  allowed_decisions: ["categorize"],
  context: {},
  created_at: "2026-01-10T00:00:00+00:00",
  updated_at: "2026-01-10T00:00:00+00:00",
};

const blockingReview = {
  id: "00000000-0000-0000-0000-000000000014",
  subject_type: "source_artifact",
  subject_id: "00000000-0000-0000-0000-000000000015",
  condition_code: "extraction_failed",
  severity: "blocking",
  status: "pending",
  version: 1,
  allowed_decisions: ["retry", "keep_quarantine"],
  context: {
    raw: "dbs-live-fresh-2026-08.pdf",
    account: "DBS Live Fresh",
    body: "Source Artifact dbs-live-fresh-2026-08.pdf failed validation.",
    claims: ["No Claims created."],
  },
  created_at: "2026-01-07T00:00:00+00:00",
  updated_at: "2026-01-07T00:00:00+00:00",
};

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.location.hash = "";
});

describe("App", () => {
  it("loads a workspace and categorizes a Transaction through the protected owner resource", async () => {
    seedOnboarded();
    window.location.hash = "#/overview";
    const fetchMock = mockWorkspace({
      transactions: [transaction],
      reviews: [pendingReview],
      categories: [
        {
          id: "00000000-0000-0000-0000-000000000099",
          name: "Synthetic Food",
          parent_id: null,
          active: true,
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Billzebub")).toBeInTheDocument();
    expect(await screen.findByText("Synthetic Coffee")).toBeInTheDocument();
    expect(screen.getByText("−SGD 12.34")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Synthetic Coffee/ }));
    fireEvent.change(
      await screen.findByLabelText("Category for Synthetic Coffee"),
      {
        target: { value: "00000000-0000-0000-0000-000000000099" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Categorize" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000010/category",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            category_id: "00000000-0000-0000-0000-000000000099",
          }),
        }),
      );
    });
    const categorizeCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).endsWith("/category"),
    );
    expect(categorizeCall?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          "If-Match": '"transaction:00000000-0000-0000-0000-000000000010:v1"',
          "X-Billzebub-CSRF": "bzb-spa",
        }),
      }),
    );
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("Categorized")).toBeInTheDocument();
  });

  it("keeps Quiet Rail chrome when the API is down", async () => {
    seedOnboarded();
    window.location.hash = "#/overview";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    render(<App />);

    expect(await screen.findByText("Billzebub")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The local workspace is unavailable. Check the API and refresh.",
    );
    expect(
      screen.getByText(
        "No trusted Transactions yet. Process an accepted statement to begin.",
      ),
    ).toBeInTheDocument();
  });

  it("posts a permitted Review decision from the two-pane desk", async () => {
    seedOnboarded();
    window.location.hash = "#/review";
    const fetchMock = mockWorkspace({
      transactions: [transaction],
      reviews: [blockingReview],
      categories: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Failed Extraction" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry Extraction" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/reviews/00000000-0000-0000-0000-000000000014/decisions",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ choice: "retry" }),
        }),
      );
    });
  });
});

describe("formatMoney", () => {
  it("formats a negative Posted Amount the way the archive shows it", () => {
    expect(formatMoney({ amount: "-12.34", currency: "SGD" })).toBe(
      "−SGD 12.34",
    );
  });
});

describe("parseHash", () => {
  it("defaults an empty hash to Setup before onboarding and Overview after", () => {
    expect(parseHash("", false).page).toBe("setup");
    expect(parseHash("", true).page).toBe("overview");
    expect(
      hashFor({
        page: "review",
        reviewFilter: "blocking",
        confirmation: "",
        drawerId: null,
      }),
    ).toBe("#/review/blocking");
  });
});

describe("setup gates", () => {
  it("blocks Continue until each Setup gate is met", () => {
    let state: SetupState = {
      ...defaultSetupState,
      selectedAccountIds: [],
      enabledCategories: [],
      probe: "idle",
      extract: "idle",
    };
    expect(stepValid(state, 0)).toBe(true);
    expect(stepValid(state, 1)).toBe(false);
    state = reduceSetup(state, { type: "toggleAccount", id: "dbs" });
    expect(stepValid(state, 1)).toBe(true);
    expect(stepValid(state, 2)).toBe(false);
    state = reduceSetup(state, { type: "probeOk" });
    expect(stepValid(state, 2)).toBe(true);
    expect(stepValid(state, 3)).toBe(false);
    state = reduceSetup(state, { type: "toggleCategory", name: "Dining" });
    expect(stepValid(state, 3)).toBe(true);
    expect(stepValid(state, 4)).toBe(false);
    state = reduceSetup(state, { type: "extractDone" });
    expect(stepValid(state, 4)).toBe(true);
    expect(firstBlockedStep(state)).toBe(4);
  });
});

function seedOnboarded(): void {
  window.localStorage.setItem(
    SETUP_STORAGE_KEY,
    JSON.stringify({
      onboarded: true,
      step: 0,
      selectedAccountIds: ["dbs", "citi", "uob", "paylah"],
      shortcut: true,
      extraCategory: "",
      enabledCategories: [
        "Groceries",
        "Dining",
        "Transport",
        "Utilities",
        "Health",
        "Shopping",
      ],
      probe: "ok",
      extract: "done",
    }),
  );
}

function mockWorkspace(input: {
  transactions: unknown[];
  reviews: unknown[];
  categories: unknown[];
}) {
  return vi.fn(async (raw: RequestInfo | URL, init?: RequestInit) => {
    const url = String(raw);
    if (url === "/api/v1/transactions") {
      return json({ items: input.transactions, next_cursor: null });
    }
    if (url === "/api/v1/reviews") {
      return json({ items: input.reviews, next_cursor: null });
    }
    if (url === "/api/v1/categories") {
      return json({ items: input.categories });
    }
    if (url.endsWith("/category") && init?.method === "PUT") {
      return json({
        ...transaction,
        version: 2,
        category_splits: [
          {
            id: "00000000-0000-0000-0000-000000000099",
            name: "Synthetic Food",
            amount: { amount: "12.34", currency: "SGD" },
          },
        ],
        reviews: [],
      });
    }
    if (url.endsWith("/decisions") && init?.method === "POST") {
      return json({ ...blockingReview, status: "resolved" });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
