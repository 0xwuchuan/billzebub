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
import { isoDate } from "./lib/labels";
import {
  defaultSetupState,
  firstBlockedStep,
  gatesMet,
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
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
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

  it("shows the last Jev skip on a categorization Review", async () => {
    seedOnboarded();
    window.location.hash = "#/review";
    const fetchMock = mockWorkspace({
      transactions: [transaction],
      reviews: [
        {
          ...pendingReview,
          context: {
            jev_attempt: {
              attempted_at: "2026-01-10T12:00:00+00:00",
              model: "jev-1.13.0",
              action: "skip",
              choice: "Synthetic Food",
              choice_confidence: "0.49",
              noul: "0.40",
              category_id: null,
              category_name: null,
              error_class: null,
              error_message: null,
            },
          },
        },
      ],
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
      await screen.findByText("Jev skip · Synthetic Food · 0.49"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Review details")).not.toBeInTheDocument();
    expect(screen.queryByText("Last Jev attempt")).not.toBeInTheDocument();
    expect(screen.queryByText("jev-1.13.0")).not.toBeInTheDocument();
    expect(screen.queryByText("0.40")).not.toBeInTheDocument();
  });

  it("categorizes from Review context when the Transaction list misses", async () => {
    seedOnboarded();
    window.location.hash = "#/review";
    const fetchMock = mockWorkspace({
      transactions: [],
      reviews: [
        {
          ...pendingReview,
          context: {
            transaction_id: transaction.id,
            counterparty: "Synthetic Orphan Cafe",
            amount: "-18.50",
            currency: "SGD",
            account: "Synthetic Card",
            effective_date: "2026-01-10",
            version: 1,
          },
        },
      ],
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
      await screen.findByRole("heading", { name: "Synthetic Orphan Cafe" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("SGD 18.50").length).toBeGreaterThan(0);
    expect(screen.queryByText("Review details")).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByLabelText("Category for Synthetic Orphan Cafe"),
      {
        target: { value: "00000000-0000-0000-0000-000000000099" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Assign Category" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000010/category",
        expect.objectContaining({
          method: "PUT",
        }),
      );
    });
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
      await screen.findByRole("heading", { name: "Synthetic Coffee" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Category needed")).toBeInTheDocument();
    expect(screen.getAllByText("SGD 12.34").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("heading", { name: "Category needed" }),
    ).not.toBeInTheDocument();
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

  it("creates a PayLah Financial Account and Wallet alias from Onboarding", async () => {
    window.location.hash = "#/onboarding";
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
              display_label: "Synthetic Wallet Card",
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
      mockWorkspace({
        transactions: [],
        reviews: [],
        categories: [],
        accounts: [configuredAccount()],
      }),
    );

    render(<App />);

    expect(await screen.findByText("Billzebub")).toBeInTheDocument();
    expect(document.querySelector(".rail")).not.toBeNull();
    expect(document.querySelector("main.stage")).not.toBeNull();
    expect(
      screen.getAllByRole("button", { name: "Switch to light theme" }).length,
    ).toBeGreaterThan(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Open navigation", hidden: true }),
    );
    const drawer = screen.getByRole("navigation", { name: "Navigation" });
    expect(drawer).toBeVisible();
    expect(
      within(drawer).getByRole("button", { name: "Imports" }),
    ).toBeVisible();
    expect(
      within(drawer).getByRole("button", { name: "Settings" }),
    ).toBeVisible();
    expect(
      within(drawer).getByRole("button", { name: "Citi PremierMiles" }),
    ).toBeVisible();
    expect(within(drawer).getByText("Credit card")).toBeInTheDocument();
    expect(
      within(drawer).queryByRole("button", { name: "Setup" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(drawer).getByRole("button", { name: "Close navigation" }),
    );
    expect(
      screen.queryByRole("navigation", { name: "Navigation" }),
    ).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: ",", metaKey: true });
    await waitFor(() => {
      expect(window.location.hash).toBe("#/settings");
    });
  });

  it("toggles light and dark theme and persists the choice", async () => {
    seedOnboarded();
    window.location.hash = "#/overview";
    vi.stubGlobal(
      "fetch",
      mockWorkspace({ transactions: [], reviews: [], categories: [] }),
    );

    render(<App />);

    expect(await screen.findByText("Billzebub")).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");
    const toLight = screen.getAllByRole("button", {
      name: "Switch to light theme",
    })[0];
    if (toLight === undefined) {
      throw new Error("theme toggle missing");
    }
    fireEvent.click(toLight);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("bz.theme")).toBe("light");
    const toDark = screen.getAllByRole("button", {
      name: "Switch to dark theme",
    })[0];
    if (toDark === undefined) {
      throw new Error("theme toggle missing");
    }
    fireEvent.click(toDark);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("bz.theme")).toBe("dark");
  });

  it("advances to the next categorization Review after assign", async () => {
    seedOnboarded();
    window.location.hash = "#/review";
    const nextTransaction = {
      ...transaction,
      id: "00000000-0000-0000-0000-000000000020",
      counterparty: "Synthetic Grocer",
      posted_amount: { amount: "-8.00", currency: "SGD" },
    };
    const nextReview = {
      ...pendingReview,
      id: "00000000-0000-0000-0000-000000000021",
      subject_id: nextTransaction.id,
      created_at: "2026-01-11T00:00:00+00:00",
      updated_at: "2026-01-11T00:00:00+00:00",
    };
    const fetchMock = mockWorkspace({
      transactions: [transaction, nextTransaction],
      reviews: [pendingReview, nextReview],
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
      await screen.findByRole("heading", { name: "Synthetic Coffee" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Synthetic Grocer")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Category for Synthetic Coffee"), {
      target: { value: "00000000-0000-0000-0000-000000000099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign Category" }));

    expect(
      await screen.findByRole("heading", { name: "Synthetic Grocer" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Synthetic Coffee" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Category for Synthetic Grocer")).toBe(
      screen.getByRole("combobox"),
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000010/category",
        expect.objectContaining({ method: "PUT" }),
      );
    });
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
      await screen.findByRole("heading", {
        name: "dbs-live-fresh-2026-08.pdf",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Failed Extraction")).toBeInTheDocument();
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

  it("shows a Provisional Real-time Claim in Overview and Transactions without a statement", async () => {
    seedOnboarded();
    window.location.hash = "#/overview";
    const today = isoDate(new Date());
    const provisional = {
      ...transaction,
      id: "00000000-0000-0000-0000-000000000016",
      counterparty: "Synthetic Wallet Merchant",
      posted_amount: { amount: "0", currency: "SGD" },
      authorized_amount: { amount: "-12.34", currency: "SGD" },
      effective_date: today,
      category_splits: [],
      reviews: [],
    };
    vi.stubGlobal(
      "fetch",
      mockWorkspace({
        transactions: [provisional],
        reviews: [],
        categories: [],
      }),
    );

    render(<App />);

    expect(
      await screen.findByText("Synthetic Wallet Merchant"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("−SGD 12.34").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Provisional").length).toBeGreaterThan(0);
    const provisionalCell = screen.getByRole("button", {
      name: /1 awaiting a Statement Claim/,
    });
    fireEvent.click(provisionalCell);
    expect(
      await screen.findByRole("heading", { name: "Transactions" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Synthetic Wallet Merchant")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Synthetic Wallet Merchant/ }),
    );
    expect(
      await screen.findByText("Provisional Real-time Claim"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Categorize" }),
    ).not.toBeInTheDocument();
  });

  it("shows Transactions with date groups, summary totals, and a bulk bar", async () => {
    seedOnboarded();
    window.location.hash = "#/transactions";
    vi.stubGlobal(
      "fetch",
      mockWorkspace({
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
        accounts: [configuredAccount()],
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Transactions" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Filtered totals")).toHaveTextContent(
      "Total spent",
    );
    expect(screen.getByLabelText("Filtered totals")).toHaveTextContent(
      "Total income",
    );
    expect(screen.getByLabelText("Filtered totals")).toHaveTextContent("Net");
    expect(
      screen.getByRole("button", { name: "Add filter" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select Synthetic Coffee" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Credit card")).toBeInTheDocument();
    expect(screen.getByText("Citi PremierMiles")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select Synthetic Coffee" }),
    );
    expect(document.querySelector(".tx-page.has-bulk")).not.toBeNull();
    const bulk = screen.getByRole("toolbar", { name: "Bulk actions" });
    expect(bulk).toHaveTextContent("1 selected");
    expect(
      within(bulk).getByRole("button", { name: "Clear selection" }),
    ).toBeInTheDocument();
    expect(
      within(bulk).getByRole("button", { name: "Apply Category" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Synthetic Coffee/ }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Synthetic Coffee",
    );
  });

  it("lists Extractions on Imports and opens them from a Blocking review", async () => {
    seedOnboarded();
    window.location.hash = "#/imports";
    const failedImport = {
      id: "00000000-0000-0000-0000-000000000017",
      source_artifact_id: "00000000-0000-0000-0000-000000000015",
      financial_account_id: "00000000-0000-0000-0000-000000000018",
      financial_account_name: "Synthetic Statement Card",
      status: "failed",
      adapter_key: "dbs-credit-card",
      parser_version: "v1",
      statement_date: "2026-08-31",
      period_start: "2026-08-01",
      period_end: "2026-08-31",
      candidate_row_count: 0,
      claim_count: 0,
      failure_code: "account_mismatch",
      validation_report: { failure: { code: "account_mismatch" } },
      duplicate_arrivals: 0,
      active_review_id: "00000000-0000-0000-0000-000000000019",
      supersedes_extraction_id: null,
      created_at: "2026-08-31T00:00:00+00:00",
      accepted_at: null,
      dismissed_at: null,
    };
    const extractionReview = {
      ...blockingReview,
      id: "00000000-0000-0000-0000-000000000019",
      subject_type: "extraction",
      subject_id: failedImport.id,
      condition_code: "statement_extraction:account_mismatch",
    };
    vi.stubGlobal(
      "fetch",
      mockWorkspace({
        transactions: [],
        reviews: [extractionReview],
        categories: [],
        imports: [failedImport],
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Imports" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("dbs-credit-card").length).toBeGreaterThan(0);
    expect(screen.getAllByText("account_mismatch").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /dbs-credit-card/ }));
    expect(await screen.findByText("Failure code")).toBeInTheDocument();
    expect(screen.getAllByText("account_mismatch").length).toBeGreaterThan(0);
    expect(window.location.hash).toBe(
      "#/imports/00000000-0000-0000-0000-000000000017",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Open navigation", hidden: true }),
    );
    const drawer = screen.getByRole("navigation", { name: "Navigation" });
    fireEvent.click(within(drawer).getByRole("button", { name: /Review/ }));
    expect(
      await screen.findByRole("heading", { name: "Pending Review" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Import" }));
    expect(
      await screen.findByRole("heading", { name: "Imports" }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe(
      "#/imports/00000000-0000-0000-0000-000000000017",
    );
  });

  it("dismisses a failed Extraction from Imports and can show it again", async () => {
    seedOnboarded();
    window.location.hash = "#/imports";
    const failedImport = {
      id: "00000000-0000-0000-0000-000000000017",
      source_artifact_id: "00000000-0000-0000-0000-000000000015",
      financial_account_id: "00000000-0000-0000-0000-000000000018",
      financial_account_name: "Synthetic Statement Card",
      status: "failed",
      adapter_key: "apple_wallet_shortcut",
      parser_version: "2",
      statement_date: null,
      period_start: null,
      period_end: null,
      candidate_row_count: 0,
      claim_count: 0,
      failure_code: "invalid_payload_shape",
      validation_report: { failure: { code: "invalid_payload_shape" } },
      duplicate_arrivals: 0,
      active_review_id: null,
      supersedes_extraction_id: null,
      created_at: "2026-08-31T00:00:00+00:00",
      accepted_at: null,
      dismissed_at: null as string | null,
    };
    const acceptedImport = {
      ...failedImport,
      id: "00000000-0000-0000-0000-000000000018",
      status: "accepted",
      adapter_key: "citi-credit-card",
      failure_code: null,
      claim_count: 2,
      accepted_at: "2026-08-31T00:00:00+00:00",
    };
    const items = [failedImport, acceptedImport];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (raw: RequestInfo | URL, init?: RequestInit) => {
        const url = String(raw);
        if (url === "/api/v1/whoami") {
          return json({ login: "owner@example.test", name: "Owner" });
        }
        if (url === "/api/v1/transactions") {
          return json({ items: [], next_cursor: null });
        }
        if (url === "/api/v1/reviews") {
          return json({ items: [], next_cursor: null });
        }
        if (url === "/api/v1/imports" || url.startsWith("/api/v1/imports?")) {
          const includeDismissed = url.includes("include_dismissed=true");
          return json({
            items: items.filter(
              (item) => includeDismissed || item.dismissed_at === null,
            ),
          });
        }
        if (url === "/api/v1/statement-coverage") {
          return json({
            as_of: "2026-09-15",
            timezone: "Asia/Singapore",
            window_months: 6,
            accounts: [],
          });
        }
        if (url === "/api/v1/categories") {
          return json({ items: [] });
        }
        if (url === "/api/v1/financial-accounts") {
          return json({ items: [] });
        }
        if (url === "/api/v1/statement-adapters") {
          return json({ items: [] });
        }
        if (url === "/api/v1/tokens") {
          return json({ items: [] });
        }
        if (
          url === `/api/v1/imports/${failedImport.id}/dismiss` &&
          init?.method === "POST"
        ) {
          failedImport.dismissed_at = "2026-09-15T00:00:00+00:00";
          return json(failedImport);
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Imports" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Apple Wallet").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(screen.queryByText("Apple Wallet")).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("citi-credit-card").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Show dismissed" }));
    expect((await screen.findAllByText("Apple Wallet")).length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText("dismissed").length).toBeGreaterThan(0);
  });

  it("marks missing statement months and deep-links Imports by Financial Account", async () => {
    seedOnboarded();
    window.location.hash = "#/imports";
    const account = configuredAccount();
    const coveredImport = {
      id: "00000000-0000-0000-0000-000000000041",
      source_artifact_id: "00000000-0000-0000-0000-000000000040",
      financial_account_id: account.id,
      financial_account_name: account.display_name,
      status: "accepted",
      adapter_key: "citi-credit-card",
      parser_version: "v1",
      statement_date: "2026-04-30",
      period_start: "2026-04-01",
      period_end: "2026-04-30",
      candidate_row_count: 2,
      claim_count: 2,
      failure_code: null,
      validation_report: {},
      duplicate_arrivals: 0,
      active_review_id: null,
      supersedes_extraction_id: null,
      created_at: "2026-04-30T00:00:00+00:00",
      accepted_at: "2026-04-30T00:00:00+00:00",
      dismissed_at: null,
    };
    const otherImport = {
      ...coveredImport,
      id: "00000000-0000-0000-0000-000000000042",
      financial_account_id: "00000000-0000-0000-0000-000000000099",
      financial_account_name: "Other Card",
      adapter_key: "dbs-credit-card",
    };
    vi.stubGlobal(
      "fetch",
      mockWorkspace({
        transactions: [],
        reviews: [],
        categories: [
          {
            id: "00000000-0000-0000-0000-000000000099",
            name: "Dining",
            parent_id: null,
            active: true,
          },
        ],
        accounts: [account],
        imports: [coveredImport, otherImport],
        coverage: {
          as_of: "2026-09-15",
          timezone: "Asia/Singapore",
          window_months: 6,
          accounts: [
            {
              id: account.id,
              display_name: account.display_name,
              slug: account.slug,
              months: [
                { month: "2026-04", status: "present" },
                { month: "2026-05", status: "partial" },
                { month: "2026-06", status: "missing" },
                { month: "2026-07", status: "missing" },
                { month: "2026-08", status: "missing" },
                { month: "2026-09", status: "missing" },
              ],
            },
          ],
        },
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Statement coverage" }),
    ).toBeInTheDocument();
    expect(screen.getByText("present")).toBeInTheDocument();
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.getAllByText("missing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("citi-credit-card").length).toBeGreaterThan(0);
    expect(screen.getByText("dbs-credit-card")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Citi PremierMiles Jun missing",
      }),
    );
    expect(window.location.hash).toBe(`#/imports?account=${account.id}`);
    await waitFor(() => {
      expect(screen.queryByText("dbs-credit-card")).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("citi-credit-card").length).toBeGreaterThan(0);
  });

  it("never shows Onboarding when accounts and Categories already exist", async () => {
    window.location.hash = "";
    vi.stubGlobal(
      "fetch",
      mockWorkspace({
        transactions: [],
        reviews: [],
        categories: [
          {
            id: "00000000-0000-0000-0000-000000000099",
            name: "Dining",
            parent_id: null,
            active: true,
          },
        ],
        accounts: [configuredAccount()],
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "This machine keeps the history" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Onboarding ·/)).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Settings" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: "Setup" }),
    ).not.toBeInTheDocument();
    expect(["", "#/overview"]).toContain(window.location.hash);
  });

  it("shows Onboarding when the only Category is Uncategorized", async () => {
    window.location.hash = "";
    vi.stubGlobal(
      "fetch",
      mockWorkspace({
        transactions: [],
        reviews: [],
        categories: [
          {
            id: "00000000-0000-0000-0000-000000000098",
            name: "Uncategorized",
            parent_id: null,
            active: true,
          },
        ],
        accounts: [configuredAccount()],
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", {
        name: "This machine keeps the history",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Onboarding ·/)).toBeInTheDocument();
  });

  it("adds an account, alias, Category, and token from Settings", async () => {
    seedOnboarded();
    window.location.hash = "#/settings";
    const created = {
      ...configuredAccount(),
      id: "00000000-0000-0000-0000-000000000031",
      slug: "synthetic-paylah",
      display_name: "Synthetic PayLah",
      kind: "paylah",
      statement_adapter_key: null,
      inbox_ready: false,
      aliases: [],
    };
    const fetchMock = mockWorkspace({
      transactions: [],
      reviews: [],
      categories: [
        {
          id: "00000000-0000-0000-0000-000000000099",
          name: "Dining",
          parent_id: null,
          active: true,
        },
      ],
      accounts: [configuredAccount()],
    });
    fetchMock.mockImplementation(
      async (raw: RequestInfo | URL, init?: RequestInit) => {
        const url = String(raw);
        if (url === "/api/v1/financial-accounts" && init?.method === "POST") {
          return json(created, 201);
        }
        if (url.endsWith("/aliases") && init?.method === "POST") {
          return json(
            {
              id: "00000000-0000-0000-0000-000000000032",
              alias_kind: "apple_wallet_card",
              display_label: "Citi PremierMiles",
            },
            201,
          );
        }
        if (url === "/api/v1/categories" && init?.method === "POST") {
          return json(
            {
              id: "00000000-0000-0000-0000-000000000033",
              name: "Pets",
              parent_id: null,
              active: true,
            },
            201,
          );
        }
        if (url === "/api/v1/tokens" && init?.method === "POST") {
          return json(
            {
              id: "00000000-0000-0000-0000-000000000034",
              name: "Apple Shortcut",
              prefix: "abcd1234efgh",
              scopes: ["shortcut:claims:create"],
              created_at: "2026-01-10T00:00:00+00:00",
              last_used_at: null,
              plaintext: "bzb_v1_abcd1234efgh_once",
            },
            201,
          );
        }
        return mockWorkspace({
          transactions: [],
          reviews: [],
          categories: [
            {
              id: "00000000-0000-0000-0000-000000000099",
              name: "Dining",
              parent_id: null,
              active: true,
            },
          ],
          accounts: [configuredAccount()],
        })(raw, init);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Settings" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Onboarding ·/)).not.toBeInTheDocument();
    expect(screen.getByText(/Citi PremierMiles • 8899/)).toBeInTheDocument();
    expect(screen.queryByText(/Sy•/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
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
    expect(screen.getAllByText("Synthetic PayLah").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Map card" }));
    fireEvent.change(screen.getByLabelText("Apple Wallet card label"), {
      target: { value: "Citi Rewards" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Map Wallet card" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/financial-accounts/00000000-0000-0000-0000-000000000021/aliases",
        expect.objectContaining({ method: "POST" }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Category" }));
    fireEvent.change(screen.getByLabelText("Category name"), {
      target: { value: "Pets" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Category" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/categories",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ name: "Pets", parent_id: null }),
        }),
      );
    });
    expect(screen.getAllByText("Pets").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Issue token" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Issue Shortcut token" }),
    );
    expect(
      await screen.findByText("bzb_v1_abcd1234efgh_once"),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem(SETUP_STORAGE_KEY)).not.toContain(
      "bzb_v1_",
    );
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
  it("defaults an empty hash to Onboarding before gates and Overview after", () => {
    expect(parseHash("", false).page).toBe("onboarding");
    expect(parseHash("", true).page).toBe("overview");
    expect(parseHash("#/setup", false).page).toBe("onboarding");
    expect(parseHash("#/setup", true).page).toBe("settings");
    expect(parseHash("#/onboarding", true).page).toBe("settings");
    expect(parseHash("#/settings", true).page).toBe("settings");
    expect(parseHash("#/spending", true).page).toBe("spending");
    expect(hashFor({ ...parseHash("#/spending", true) })).toBe("#/spending");
    expect(
      hashFor({
        page: "review",
        reviewFilter: "blocking",
        confirmation: "",
        drawerId: null,
        importId: null,
        accountId: null,
      }),
    ).toBe("#/review/blocking");
    expect(hashFor({ ...parseHash("#/settings", true) })).toBe("#/settings");
    expect(parseHash("#/imports", true).page).toBe("imports");
    expect(
      parseHash("#/imports/00000000-0000-0000-0000-000000000099", true),
    ).toEqual({
      page: "imports",
      reviewFilter: "",
      confirmation: "",
      drawerId: null,
      importId: "00000000-0000-0000-0000-000000000099",
      accountId: null,
    });
    expect(
      parseHash("#/imports?account=00000000-0000-0000-0000-000000000021", true),
    ).toEqual({
      page: "imports",
      reviewFilter: "",
      confirmation: "",
      drawerId: null,
      importId: null,
      accountId: "00000000-0000-0000-0000-000000000021",
    });
    expect(
      hashFor({
        page: "imports",
        reviewFilter: "",
        confirmation: "",
        drawerId: null,
        importId: null,
        accountId: "00000000-0000-0000-0000-000000000021",
      }),
    ).toBe("#/imports?account=00000000-0000-0000-0000-000000000021");
  });
});

describe("setup gates", () => {
  it("blocks Continue until each Onboarding gate is met", () => {
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
    expect(gatesMet(empty)).toBe(false);
    expect(gatesMet(accounts)).toBe(false);
    expect(gatesMet(ready)).toBe(true);
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

function configuredAccount() {
  return {
    id: "00000000-0000-0000-0000-000000000021",
    slug: "citi-premiermiles",
    display_name: "Citi PremierMiles",
    institution: "citi",
    kind: "credit_card",
    default_currency: "SGD",
    statement_adapter_key: "citi-credit-card",
    active: true,
    password_configured: true,
    inbox_ready: true,
    aliases: [
      {
        id: "00000000-0000-0000-0000-000000000022",
        alias_kind: "apple_wallet_card",
        display_label: "Citi PremierMiles 8899",
      },
    ],
  };
}

function mockWorkspace(input: {
  transactions: unknown[];
  reviews: unknown[];
  categories: unknown[];
  accounts?: unknown[];
  tokens?: unknown[];
  adapters?: unknown[];
  imports?: unknown[];
  coverage?: unknown;
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
    if (url === "/api/v1/imports" || url.startsWith("/api/v1/imports?")) {
      const includeDismissed = url.includes("include_dismissed=true");
      const items = (input.imports ?? []).filter((item) => {
        if (
          includeDismissed ||
          typeof item !== "object" ||
          item === null ||
          !("dismissed_at" in item)
        ) {
          return true;
        }
        return item.dismissed_at === null;
      });
      return json({ items });
    }
    if (url === "/api/v1/statement-coverage") {
      return json(
        input.coverage ?? {
          as_of: "2026-09-15",
          timezone: "Asia/Singapore",
          window_months: 6,
          accounts: [],
        },
      );
    }
    if (url === "/api/v1/imports/dismiss-failed" && init?.method === "POST") {
      return json({ dismissed_count: 0 });
    }
    if (url.endsWith("/dismiss") && init?.method === "POST") {
      const extractionId = url.slice(
        "/api/v1/imports/".length,
        url.length - "/dismiss".length,
      );
      const match = (input.imports ?? []).find((item) => {
        return (
          typeof item === "object" &&
          item !== null &&
          "id" in item &&
          item.id === extractionId
        );
      });
      if (match !== undefined && typeof match === "object") {
        return json({ ...match, dismissed_at: "2026-09-15T00:00:00+00:00" });
      }
    }
    if (url.startsWith("/api/v1/imports/")) {
      const extractionId = url.slice("/api/v1/imports/".length);
      const match = (input.imports ?? []).find((item) => {
        return (
          typeof item === "object" &&
          item !== null &&
          "id" in item &&
          item.id === extractionId
        );
      });
      if (match !== undefined) {
        return json(match);
      }
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
      const transactionId = url.slice(
        "/api/v1/transactions/".length,
        url.length - "/category".length,
      );
      const match = input.transactions.find((item) => {
        return (
          typeof item === "object" &&
          item !== null &&
          "id" in item &&
          item.id === transactionId
        );
      });
      const source =
        match !== undefined && typeof match === "object"
          ? { ...transaction, ...match }
          : transaction;
      return json({
        ...source,
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
