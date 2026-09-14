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
  stepIndexValid,
  stepValid,
  type SetupGates,
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

  it("categorizes a Transaction from the Review queue", async () => {
    seedOnboarded();
    window.location.hash = "#/review";
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

    expect(
      await screen.findByRole("heading", { name: "Category needed" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Category for Synthetic Coffee"), {
      target: { value: "00000000-0000-0000-0000-000000000099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign Category" }));

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
  });

  it("creates a PayLah Financial Account and Wallet alias from Setup", async () => {
    window.location.hash = "#/setup";
    const created = {
      id: "00000000-0000-0000-0000-000000000021",
      slug: "synthetic-paylah",
      display_name: "Synthetic PayLah",
      institution: "dbs",
      kind: "paylah",
      default_currency: "SGD",
      statement_adapter_key: null,
      active: true,
      password_configured: false,
      inbox_ready: false,
      aliases: [],
    };
    const fetchMock = mockWorkspace({
      transactions: [],
      reviews: [],
      categories: [],
      accounts: [],
    });
    fetchMock.mockImplementation(
      async (raw: RequestInfo | URL, init?: RequestInit) => {
        const url = String(raw);
        if (url === "/api/v1/financial-accounts" && init?.method === "POST") {
          return json(created, 201);
        }
        if (url.endsWith("/aliases") && init?.method === "POST") {
          const body = JSON.parse(String(init.body)) as { card_label: string };
          expect(body.card_label).toBe("Synthetic Wallet Card");
          return json(
            {
              id: "00000000-0000-0000-0000-000000000022",
              alias_kind: "apple_wallet_card",
              masked_value: "Sy••••••rd",
            },
            201,
          );
        }
        return mockWorkspace({
          transactions: [],
          reviews: [],
          categories: [],
          accounts: [created],
        })(raw, init);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", {
        name: "This machine keeps the history",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByRole("heading", {
        name: "Watch these Financial Accounts",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Citi PremierMiles" }));
    expect(screen.getByLabelText("Slug")).toHaveValue("citi-premiermiles");
    expect(screen.getByLabelText("Display name")).toHaveValue(
      "Citi PremierMiles",
    );
    expect(screen.getByLabelText("Statement adapter")).toHaveValue(
      "citi-credit-card",
    );
    fireEvent.click(screen.getByRole("button", { name: "DBS Woman's World" }));
    expect(screen.getByLabelText("Slug")).toHaveValue("dbs-womans-world");
    expect(screen.getByLabelText("Display name")).toHaveValue(
      "DBS Woman's World",
    );
    expect(screen.getByLabelText("Statement adapter")).toHaveValue(
      "dbs-credit-card",
    );
    fireEvent.change(screen.getByLabelText("Kind"), {
      target: { value: "paylah" },
    });
    fireEvent.change(screen.getByLabelText("Slug"), {
      target: { value: "synthetic-paylah" },
    });
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Synthetic PayLah" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create Financial Account" }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/financial-accounts",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            slug: "synthetic-paylah",
            display_name: "Synthetic PayLah",
            institution: "dbs",
            kind: "paylah",
            default_currency: "SGD",
          }),
        }),
      );
    });
    expect(window.localStorage.getItem(SETUP_STORAGE_KEY)).not.toContain(
      "bzb_v1_",
    );
  });

  it("exposes a mobile navigation control on the Quiet Rail shell", async () => {
    seedOnboarded();
    window.location.hash = "#/overview";
    vi.stubGlobal(
      "fetch",
      mockWorkspace({ transactions: [], reviews: [], categories: [] }),
    );

    render(<App />);

    expect(await screen.findByText("Billzebub")).toBeInTheDocument();
    expect(document.querySelector(".rail")).not.toBeNull();
    expect(document.querySelector("main.stage")).not.toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Open navigation", hidden: true }),
    );
    const drawer = screen.getByRole("navigation", { name: "Navigation" });
    expect(drawer).toBeVisible();
    fireEvent.click(
      within(drawer).getByRole("button", { name: "Close navigation" }),
    );
    expect(
      screen.queryByRole("navigation", { name: "Navigation" }),
    ).not.toBeInTheDocument();
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
    const empty: SetupGates = { accountCount: 0, categoryCount: 0 };
    const accounts: SetupGates = { accountCount: 1, categoryCount: 0 };
    const ready: SetupGates = { accountCount: 1, categoryCount: 1 };
    let state: SetupState = defaultSetupState;
    expect(stepValid(state, empty)).toBe(true);
    expect(stepIndexValid(1, empty)).toBe(false);
    expect(stepIndexValid(1, accounts)).toBe(true);
    expect(stepIndexValid(3, accounts)).toBe(false);
    expect(stepIndexValid(3, ready)).toBe(true);
    expect(stepIndexValid(4, ready)).toBe(true);
    expect(firstBlockedStep(state, empty)).toBe(1);
    state = reduceSetup(state, { type: "advance" }, empty);
    expect(state.step).toBe(1);
    state = reduceSetup(state, { type: "advance" }, accounts);
    expect(state.step).toBe(2);
  });
});

function seedOnboarded(): void {
  window.localStorage.setItem(
    SETUP_STORAGE_KEY,
    JSON.stringify({
      onboarded: true,
      step: 0,
    }),
  );
}

function mockWorkspace(input: {
  transactions: unknown[];
  reviews: unknown[];
  categories: unknown[];
  accounts?: unknown[];
  tokens?: unknown[];
  adapters?: unknown[];
  identity?: { login: string; name: string };
}) {
  return vi.fn(async (raw: RequestInfo | URL, init?: RequestInit) => {
    const url = String(raw);
    if (url === "/api/v1/whoami") {
      return json(
        input.identity ?? {
          login: "owner@example.test",
          name: "Owner",
        },
      );
    }
    if (url === "/api/v1/transactions") {
      return json({ items: input.transactions, next_cursor: null });
    }
    if (url === "/api/v1/reviews") {
      return json({ items: input.reviews, next_cursor: null });
    }
    if (url === "/api/v1/categories") {
      return json({ items: input.categories });
    }
    if (url === "/api/v1/financial-accounts") {
      return json({ items: input.accounts ?? [] });
    }
    if (url === "/api/v1/statement-adapters") {
      return json({
        items: input.adapters ?? [
          { key: "dbs-credit-card", institution: "dbs", kind: "credit_card" },
          { key: "citi-credit-card", institution: "citi", kind: "credit_card" },
          { key: "uob-credit-card", institution: "uob", kind: "credit_card" },
        ],
      });
    }
    if (url === "/api/v1/tokens") {
      return json({ items: input.tokens ?? [] });
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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
