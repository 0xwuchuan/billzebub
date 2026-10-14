/**
 * FAKE EXAMPLE DATA for the dev-only `?data=` stress toggle.
 * Every name, amount, account, and identifier here is invented.
 * Nothing in this module is loaded in production builds, and nothing
 * here is written to the database.
 *
 * Limits (schema / API):
 * - counterparty: 300 (transactions, recurrings)
 * - account display_name: 160, institution: 80, slug: 80
 * - category name: 120
 * - adapter_key, parser_version, failure_code: 120
 * - review choice: 120
 * - recurring notes: 2000
 * - claim raw_description: unbounded text
 */

import type {
  Category,
  FinancialAccount,
  ImportRecord,
  RecurringSeries,
  RecurringSummary,
  Review,
  StatementCoverageReport,
  Transaction,
} from "../api";
import type { WorkspaceSnapshot } from "../hooks/useWorkspace";
import type { FixtureMode } from "./fixtureMode";

const HUGE = "1234567.89";
const URL_MERCHANT =
  "https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved";
const EMAIL_MERCHANT =
  "bartholomew.fitzgerald@northwind-industries-holdings.example.com";
const UUID_MERCHANT = "9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f";

export type RecurringFixture = {
  proposed: RecurringSeries[];
  active: RecurringSeries[];
  paused: RecurringSeries[];
  summary: RecurringSummary | null;
};

export function workspaceFor(
  mode: FixtureMode,
  options: { includeDismissed?: boolean } = {},
): WorkspaceSnapshot {
  const today = new Date();
  if (mode === "empty") {
    return emptyWorkspace(today);
  }
  if (mode === "one") {
    return oneWorkspace(today);
  }
  const transactions =
    mode === "1000" ? thousandTransactions(today) : worstTransactions(today);
  const snapshot = populatedWorkspace(today, transactions);
  if (options.includeDismissed) {
    return snapshot;
  }
  return {
    ...snapshot,
    imports: snapshot.imports.filter((item) => item.dismissed_at === null),
  };
}

export function recurringsFor(mode: FixtureMode): RecurringFixture {
  const today = new Date();
  if (mode === "empty") {
    return { proposed: [], active: [], paused: [], summary: null };
  }
  if (mode === "one") {
    return oneRecurrings(today);
  }
  return worstRecurrings(today);
}

function emptyWorkspace(today: Date): WorkspaceSnapshot {
  return {
    identity: { login: "example.owner@example.com", name: "Example Owner" },
    transactions: { items: [], next_cursor: null },
    reviews: [],
    imports: [],
    coverage: coverage(today, []),
    categories: [],
    accounts: [],
    adapters: [],
    tokens: [],
  };
}

function oneWorkspace(today: Date): WorkspaceSnapshot {
  const card = account({
    id: "example-acc-one",
    slug: "example-card",
    display_name: "Example Card",
    institution: "example",
    kind: "credit_card",
  });
  const category = categoryRow("example-cat-groceries", "Groceries");
  const transaction = tx({
    id: "example-tx-one",
    account: card,
    counterparty: "Example Cafe",
    amount: "4.50",
    kind: "expense",
    date: iso(today),
    splits: [split(category, "4.50")],
  });
  return {
    identity: { login: "example.owner@example.com", name: "Example Owner" },
    transactions: { items: [transaction], next_cursor: null },
    reviews: [
      review({
        id: "example-review-one",
        severity: "attention",
        condition: "categorization_needed",
        decisions: ["assign"],
        created: iso(today),
        context: {
          transaction_id: transaction.id,
          counterparty: transaction.counterparty,
          account: card.display_name,
          amount: "4.50",
          currency: "SGD",
          effective_date: transaction.effective_date,
          kind: "expense",
        },
      }),
    ],
    imports: [
      importRow({
        id: "example-import-one",
        account: card,
        status: "accepted",
        adapter: "example-statement",
        failure: null,
        claims: 1,
        date: iso(today),
      }),
    ],
    coverage: coverage(today, [card]),
    categories: [category, categoryRow("example-cat-uncat", "Uncategorized")],
    accounts: [card],
    adapters: [
      { key: "example-statement", institution: "example", kind: "credit_card" },
    ],
    tokens: [],
  };
}

function populatedWorkspace(
  today: Date,
  transactions: Transaction[],
): WorkspaceSnapshot {
  const accounts = worstAccounts();
  const categories = worstCategories();
  const imports = worstImports(today, accounts);
  return {
    identity: {
      login: "example.owner@example.com",
      name: "Aleksandra Wiśniewska-Kowalczyk",
    },
    transactions: { items: transactions, next_cursor: null },
    reviews: worstReviews(today, transactions, accounts, imports),
    imports,
    coverage: coverage(today, accounts),
    categories,
    accounts,
    adapters: [
      { key: "dbs-credit-card", institution: "dbs", kind: "credit_card" },
      { key: "example-statement", institution: "example", kind: "credit_card" },
    ],
    tokens: [],
  };
}

function worstAccounts(): FinancialAccount[] {
  return [
    account({
      id: "example-acc-long",
      slug: "example-long-card",
      display_name: atLimit(
        "DBS Woman's World — Aleksandra Wiśniewska-Kowalczyk household card",
        160,
      ),
      institution: "dbs",
      kind: "credit_card",
      alias: atLimit(
        "Aleksandra Wiśniewska-Kowalczyk Visa Infinite example label",
        160,
      ),
    }),
    account({
      id: "example-acc-jo",
      slug: "jo",
      display_name: "Jo",
      institution: "citi",
      kind: "credit_card",
    }),
    account({
      id: "example-acc-url",
      slug: "example-url-card",
      display_name: URL_MERCHANT.slice(0, 160),
      institution: "uob",
      kind: "credit_card",
    }),
    account({
      id: "example-acc-paylah",
      slug: "example-paylah",
      display_name: "王秀英 PayLah",
      institution: "dbs",
      kind: "paylah",
    }),
  ];
}

function worstCategories(): Category[] {
  return [
    categoryRow("example-cat-groceries", "Groceries"),
    categoryRow("example-cat-dining", "Dining"),
    categoryRow("example-cat-transport", "Transport"),
    categoryRow(
      "example-cat-long",
      atLimit(
        "Senior Product Design Engineer, Platform Infrastructure and member dining",
        120,
      ),
    ),
    categoryRow("example-cat-uncat", "Uncategorized"),
  ];
}

function worstTransactions(today: Date): Transaction[] {
  const [long, jo, url, paylah] = worstAccounts();
  const categories = worstCategories();
  const groceries = categories[0];
  const dining = categories[1];
  const longCategory = categories[3];
  if (
    long === undefined ||
    jo === undefined ||
    url === undefined ||
    paylah === undefined ||
    groceries === undefined ||
    dining === undefined ||
    longCategory === undefined
  ) {
    return [];
  }
  const rows: Array<Parameters<typeof tx>[0]> = [
    {
      id: "example-tx-huge",
      account: long,
      counterparty: atLimit(
        "Aleksandra Wiśniewska-Kowalczyk Consulting and Design Studio Private Limited, trading as Northwind Industries Holdings",
        300,
      ),
      amount: HUGE,
      kind: "expense",
      date: iso(today),
      splits: [split(groceries, HUGE)],
      review: true,
    },
    {
      id: "example-tx-url",
      account: url,
      counterparty: URL_MERCHANT,
      amount: "86.40",
      kind: "expense",
      date: iso(today),
      splits: [],
    },
    {
      id: "example-tx-cjk",
      account: paylah,
      counterparty: "王秀英",
      amount: "12.00",
      kind: "expense",
      date: iso(shift(today, -1)),
      splits: [split(dining, "12.00")],
    },
    {
      id: "example-tx-emoji",
      account: jo,
      counterparty: "🦊 Fox Street Market",
      amount: "-1284.00",
      kind: "refund",
      date: iso(today),
      splits: [split(groceries, "1284.00")],
    },
    {
      id: "example-tx-missing-name",
      account: long,
      counterparty: "",
      amount: "8.50",
      kind: "expense",
      date: iso(today),
      splits: [],
    },
    {
      id: "example-tx-zwj",
      account: jo,
      counterparty: "👩🏽‍💻 Priya Design Studio",
      amount: "0.00",
      authorized: "64.00",
      kind: "expense",
      date: iso(today),
      splits: [split(longCategory, "64.00")],
    },
    {
      id: "example-tx-viet",
      account: long,
      counterparty: "Đặng Thị Ngọc Hân",
      amount: "19.80",
      kind: "expense",
      date: iso(shift(today, -2)),
      splits: [split(dining, "19.80")],
    },
    {
      id: "example-tx-email",
      account: url,
      counterparty: EMAIL_MERCHANT,
      amount: "0.10",
      kind: "expense",
      date: iso(shift(today, -1)),
      splits: [],
    },
    {
      id: "example-tx-uuid",
      account: jo,
      counterparty: UUID_MERCHANT,
      amount: "0.20",
      kind: "expense",
      date: iso(shift(today, -3)),
      splits: [split(groceries, "0.20")],
    },
    {
      id: "example-tx-rtl",
      account: paylah,
      counterparty: "نور الهدى عبد الرحمن",
      amount: "42.50",
      kind: "expense",
      date: iso(today),
      splits: [split(dining, "42.50")],
    },
    {
      id: "example-tx-script",
      account: jo,
      counterparty: "<script>alert(1)</script>",
      amount: "1.00",
      kind: "expense",
      date: iso(shift(today, -1)),
      splits: [],
    },
    {
      id: "example-tx-entities",
      account: jo,
      counterparty: "Fish & Chips &amp; **bold**",
      amount: "15.00",
      kind: "expense",
      date: iso(shift(today, -4)),
      splits: [split(dining, "15.00")],
    },
    {
      id: "example-tx-newline",
      account: long,
      counterparty: "Line one\nLine two Market",
      amount: "7.25",
      kind: "expense",
      date: iso(shift(today, -1)),
      splits: [split(groceries, "7.25")],
    },
    {
      id: "example-tx-jo",
      account: jo,
      counterparty: "Jo",
      amount: "3.00",
      kind: "expense",
      date: iso(today),
      splits: [split(groceries, "3.00")],
    },
    {
      id: "example-tx-j",
      account: jo,
      counterparty: "J",
      amount: "1.00",
      kind: "transfer",
      date: iso(today),
      splits: [],
    },
    {
      id: "example-tx-spaces",
      account: long,
      counterparty: "  Sam   Lee ",
      amount: "6.60",
      kind: "expense",
      date: iso(shift(today, -5)),
      splits: [split(dining, "6.60")],
    },
    {
      id: "example-tx-german",
      account: long,
      counterparty: "Benachrichtigungseinstellungen GmbH",
      amount: "99.00",
      kind: "expense",
      date: iso(shift(today, -6)),
      splits: [split(longCategory, "99.00")],
    },
    {
      id: "example-tx-refund",
      account: url,
      counterparty: "Ólafur Darri Ólafsson",
      amount: "-42.50",
      kind: "refund",
      date: iso(today),
      splits: [],
    },
    {
      id: "example-tx-zero",
      account: paylah,
      counterparty: "Example Zero Auth",
      amount: "0.00",
      kind: "expense",
      date: iso(shift(today, -2)),
      splits: [split(groceries, "0.00")],
    },
    {
      id: "example-tx-income",
      account: long,
      counterparty: "Christopher Alexander Montgomery III",
      amount: "1284.00",
      kind: "income",
      date: iso(today),
      splits: [],
    },
    {
      id: "example-tx-file",
      account: url,
      counterparty:
        "Q3 Board Deck — FINAL (revised) v12 [approved by legal].pdf",
      amount: "250.00",
      kind: "expense",
      date: iso(shift(today, -8)),
      splits: [split(longCategory, "250.00")],
    },
  ];
  return [...rows.map((row) => tx(row)), ...merchantCharges(jo, today)];
}

function merchantCharges(
  account: FinancialAccount,
  today: Date,
): Transaction[] {
  const charges: Array<[string, string, string, number]> = [
    ["example-tx-spotify-1", "Example Spotify", "11.98", 0],
    ["example-tx-spotify-2", "Example Spotify SG", "11.98", 1],
    ["example-tx-spotify-3", "Example Spotify 1234", "12.50", 2],
    ["example-tx-grocer-1", "Example Grocer Market", "42.10", 0],
    ["example-tx-grocer-2", "Example Grocer Market Pte Ltd", "18.40", 3],
  ];
  return charges.map(([id, counterparty, amount, days]) =>
    tx({
      id,
      account,
      counterparty,
      amount,
      kind: "expense",
      date: iso(shift(today, -days)),
      splits: [],
    }),
  );
}

function thousandTransactions(today: Date): Transaction[] {
  const head = worstTransactions(today);
  const [account] = worstAccounts();
  const [category] = worstCategories();
  if (account === undefined || category === undefined) {
    return head;
  }
  const merchants = [
    "Example Mart",
    "Example Transit",
    "Example Cafe",
    "Example Pharmacy",
    "Example Utilities",
  ];
  const fillers: Transaction[] = [];
  for (let index = 0; fillers.length + head.length < 1000; index += 1) {
    const merchant = merchants[index % merchants.length] ?? "Example Mart";
    const cents = (index % 8000) + 100;
    const amount = `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
    fillers.push(
      tx({
        id: `example-tx-filler-${index}`,
        account,
        counterparty: `${merchant} ${index + 1}`,
        amount,
        kind: "expense",
        date: iso(shift(today, -(index % 26))),
        splits: [split(category, amount)],
      }),
    );
  }
  return [...head, ...fillers];
}

function worstReviews(
  today: Date,
  transactions: Transaction[],
  accounts: FinancialAccount[],
  imports: ImportRecord[],
): Review[] {
  const huge = transactions.find((item) => item.id === "example-tx-huge");
  const missing = transactions.find(
    (item) => item.id === "example-tx-missing-name",
  );
  const urlTx = transactions.find((item) => item.id === "example-tx-url");
  const longAccount = accounts[0];
  const failed = imports.find((item) => item.status === "failed");
  const longChoice = atLimit(
    "approve_the_reprocessed_statement_difference_for_northwind_industries_holdings_example",
    120,
  );
  return [
    ...merchantReviews(transactions),
    review({
      id: "example-review-blocking",
      severity: "blocking",
      condition: "extraction_failed",
      decisions: [longChoice, "keep_quarantine"],
      created: iso(shift(today, -12)),
      subjectType: huge === undefined ? "extraction" : "transaction",
      subjectId: huge?.id ?? failed?.id ?? "example-review-blocking",
      context: {
        transaction_id: huge?.id ?? "",
        counterparty: huge?.counterparty ?? URL_MERCHANT,
        account: longAccount?.display_name ?? "",
        financial_account_id: longAccount?.id ?? "",
        amount: HUGE,
        currency: "SGD",
        effective_date: huge?.effective_date ?? iso(today),
        kind: "expense",
        raw: URL_MERCHANT,
        body: `${URL_MERCHANT}\nStatement text did not match a known adapter. Literal markup <b>not bold</b> and &amp; must stay escaped. ${"Example rejection detail. ".repeat(12)}`,
        claims: [EMAIL_MERCHANT, UUID_MERCHANT],
      },
    }),
    review({
      id: "example-review-category",
      severity: "attention",
      condition: "categorization_needed",
      decisions: ["assign"],
      created: iso(today),
      subjectType: "transaction",
      subjectId: urlTx?.id ?? "example-tx-url",
      context: {
        transaction_id: urlTx?.id ?? "",
        counterparty: urlTx?.counterparty ?? URL_MERCHANT,
        account: urlTx?.financial_account.name ?? "",
        amount: "86.40",
        currency: "SGD",
        effective_date: urlTx?.effective_date ?? iso(today),
        kind: "expense",
        jev_attempt: {
          attempted_at: iso(today),
          model: "example-model",
          action: "skip",
          choice: "Benachrichtigungseinstellungen",
          choice_confidence: "0.42",
          noul: "example",
          category_id: null,
          category_name: null,
          error_class: null,
          error_message: null,
        },
      },
    }),
    review({
      id: "example-review-missing",
      severity: "attention",
      condition: "categorization_needed",
      decisions: ["assign"],
      created: iso(shift(today, -1)),
      subjectType: "transaction",
      subjectId: missing?.id ?? "example-tx-missing-name",
      context: {
        transaction_id: missing?.id ?? "",
        counterparty: "",
        account: "",
        amount: "8.50",
        currency: "SGD",
        effective_date: missing?.effective_date ?? iso(today),
        kind: "expense",
      },
    }),
    review({
      id: "example-review-wallet",
      severity: "blocking",
      condition: "apple_wallet_unmapped_card",
      decisions: ["configure_card_alias"],
      created: iso(shift(today, -3)),
      subjectType: "source_artifact",
      subjectId: "example-artifact-wallet",
      context: {
        account: atLimit(
          "Aleksandra Wiśniewska-Kowalczyk Visa Infinite example label",
          160,
        ),
        raw: "🦊 Fox Street Market",
        body: "Wallet instrument did not match a card alias. Example payload only.",
      },
    }),
    review({
      id: "example-review-script",
      severity: "attention",
      condition: "shortcut_payload_invalid",
      decisions: ["keep_quarantine"],
      created: iso(shift(today, -1)),
      subjectType: "source_artifact",
      subjectId: "example-artifact-script",
      context: {
        raw: "<script>alert(1)</script>",
        body: "Shortcut JSON was rejected. The body is example text, not a payload to execute.",
      },
    }),
  ];
}

function worstImports(
  today: Date,
  accounts: FinancialAccount[],
): ImportRecord[] {
  const long = accounts[0];
  const url = accounts[2];
  const adapter = atLimit(
    "dbs-credit-card-northwind-industries-holdings-singapore-representative-office-example",
    120,
  );
  const failure = atLimit(
    "unsupported_source_northwind-industries-holdings-shortcut-payload-example-9f8e7d6c",
    120,
  );
  return [
    importRow({
      id: "example-import-failed-url",
      account: long,
      status: "failed",
      adapter,
      failure,
      claims: 0,
      date: iso(today),
      periodStart: "2026-01-01",
      periodEnd: "2026-01-31",
    }),
    importRow({
      id: "example-import-failed-short",
      account: null,
      status: "failed",
      adapter: "x",
      failure: "a",
      claims: 0,
      date: iso(shift(today, -1)),
    }),
    importRow({
      id: "example-import-accepted-many",
      account: url,
      status: "accepted",
      adapter: "example-statement",
      failure: null,
      claims: 1284,
      date: iso(shift(today, -20)),
      periodStart: iso(shift(today, -40)),
      periodEnd: iso(shift(today, -10)),
    }),
    importRow({
      id: "example-import-accepted-one",
      account: long,
      status: "accepted",
      adapter: "apple_wallet_shortcut",
      failure: null,
      claims: 1,
      date: iso(shift(today, -2)),
    }),
    importRow({
      id: "example-import-dismissed",
      account: long,
      status: "failed",
      adapter: "paylah_shortcut",
      failure: "invalid_amount",
      claims: 0,
      date: iso(shift(today, -9)),
      dismissed: true,
    }),
  ];
}

function worstRecurrings(today: Date): RecurringFixture {
  const accounts = worstAccounts();
  const categories = worstCategories();
  const longAccount = accounts[0];
  const longCategory = categories[3];
  const proposed: RecurringSeries[] = [
    series({
      id: "example-series-proposed-long",
      counterparty: atLimit(
        "Aleksandra Wiśniewska-Kowalczyk Consulting and Design Studio Private Limited",
        300,
      ),
      amount: HUGE,
      cadence: "monthly",
      next: iso(shift(today, 3)),
      categoryId: longCategory?.id ?? null,
      accountId: longAccount?.id ?? null,
      status: "proposed",
      confidence: "0.91",
      linked: 12,
    }),
    series({
      id: "example-series-proposed-url",
      counterparty: URL_MERCHANT,
      amount: "19.99",
      cadence: "monthly",
      next: iso(shift(today, 1)),
      categoryId: null,
      accountId: null,
      status: "proposed",
      confidence: "0.42",
      linked: 3,
    }),
    series({
      id: "example-series-proposed-emoji",
      counterparty: "🦊 Fox Street Market",
      amount: "48.00",
      cadence: "weekly",
      next: iso(shift(today, 2)),
      categoryId: categories[0]?.id ?? null,
      accountId: accounts[1]?.id ?? null,
      status: "proposed",
      confidence: "0.62",
      linked: 1,
    }),
    series({
      id: "example-series-proposed-cjk",
      counterparty: "王秀英",
      amount: "8.00",
      cadence: "custom_days",
      interval: 400,
      next: iso(shift(today, 6)),
      categoryId: null,
      accountId: accounts[3]?.id ?? null,
      status: "proposed",
      confidence: null,
      linked: 0,
    }),
  ];
  const active: RecurringSeries[] = [
    series({
      id: "example-series-active-huge",
      counterparty: EMAIL_MERCHANT,
      amount: HUGE,
      cadence: "monthly",
      next: iso(today),
      categoryId: longCategory?.id ?? null,
      accountId: longAccount?.id ?? null,
      status: "active",
      confidence: "0.88",
      linked: 24,
      missed: true,
    }),
    series({
      id: "example-series-active-jo",
      counterparty: "Jo",
      amount: "4.50",
      cadence: "weekly",
      next: iso(shift(today, 1)),
      categoryId: null,
      accountId: null,
      status: "active",
      confidence: "0.55",
      linked: 1,
    }),
    series({
      id: "example-series-active-viet",
      counterparty: "Đặng Thị Ngọc Hân Phở",
      amount: "42.50",
      cadence: "monthly",
      next: iso(shift(today, 20)),
      categoryId: categories[1]?.id ?? null,
      accountId: accounts[2]?.id ?? null,
      status: "active",
      confidence: "0.7",
      linked: 6,
    }),
    series({
      id: "example-series-active-file",
      counterparty: "IMG_20250914_183022_HDR_portrait_edited_edited.HEIC",
      amount: "9.90",
      cadence: "yearly",
      next: iso(shift(today, 40)),
      categoryId: categories[0]?.id ?? null,
      accountId: accounts[1]?.id ?? null,
      status: "active",
      confidence: "0.2",
      linked: 2,
    }),
  ];
  const paused: RecurringSeries[] = [
    series({
      id: "example-series-paused",
      counterparty: "Seán O'Brien-Ó Súilleabháin",
      amount: "18.00",
      cadence: "monthly",
      next: iso(shift(today, -3)),
      categoryId: null,
      accountId: longAccount?.id ?? null,
      status: "paused",
      confidence: "0.5",
      linked: 4,
    }),
  ];
  const summary: RecurringSummary = {
    month: iso(today).slice(0, 7),
    total: { amount: HUGE, currency: "SGD" },
    upcoming: [active[0], proposed[0], active[2]].filter(
      (item): item is RecurringSeries => item !== undefined,
    ),
  };
  return { proposed, active, paused, summary };
}

function oneRecurrings(today: Date): RecurringFixture {
  const proposed = series({
    id: "example-series-one-proposed",
    counterparty: "Example Gym",
    amount: "49.00",
    cadence: "monthly",
    next: iso(shift(today, 2)),
    categoryId: "example-cat-groceries",
    accountId: "example-acc-one",
    status: "proposed",
    confidence: "0.8",
    linked: 1,
  });
  const active = series({
    id: "example-series-one-active",
    counterparty: "Example Rent",
    amount: "1.00",
    cadence: "monthly",
    next: iso(shift(today, 4)),
    categoryId: null,
    accountId: "example-acc-one",
    status: "active",
    confidence: "0.9",
    linked: 1,
  });
  return {
    proposed: [proposed],
    active: [active],
    paused: [],
    summary: {
      month: iso(today).slice(0, 7),
      total: { amount: "1.00", currency: "SGD" },
      upcoming: [active],
    },
  };
}

function tx(input: {
  id: string;
  account: FinancialAccount;
  counterparty: string;
  amount: string;
  authorized?: string;
  kind: string;
  date: string;
  splits: Transaction["category_splits"];
  review?: boolean;
}): Transaction {
  return {
    id: input.id,
    version: 1,
    financial_account: {
      id: input.account.id,
      name: input.account.display_name,
    },
    counterparty: input.counterparty,
    posted_amount: { amount: input.amount, currency: "SGD" },
    authorized_amount:
      input.authorized === undefined
        ? null
        : { amount: input.authorized, currency: "SGD" },
    effective_date: input.date,
    kind: input.kind,
    category_splits: input.splits,
    reviews: input.review
      ? [
          {
            id: `${input.id}-review`,
            condition_code: "categorization_needed",
            severity: "attention",
            version: 1,
            allowed_decisions: ["assign"],
          },
        ]
      : [],
  };
}

function merchantReviews(transactions: Transaction[]): Review[] {
  return transactions
    .filter(
      (item) =>
        item.id.startsWith("example-tx-spotify") ||
        item.id.startsWith("example-tx-grocer"),
    )
    .map((item) =>
      review({
        id: `${item.id}-group`,
        severity: "attention",
        condition: "categorization_needed",
        decisions: ["assign"],
        created: item.effective_date,
        subjectId: item.id,
        context: {
          transaction_id: item.id,
          counterparty: item.counterparty,
          amount: item.posted_amount.amount,
          currency: "SGD",
          effective_date: item.effective_date,
          kind: "expense",
        },
      }),
    );
}

function review(input: {
  id: string;
  severity: "attention" | "blocking";
  condition: string;
  decisions: string[];
  created: string;
  subjectType?: string;
  subjectId?: string;
  context: Record<string, unknown>;
}): Review {
  return {
    id: input.id,
    subject_type: input.subjectType ?? "transaction",
    subject_id: input.subjectId ?? input.id,
    condition_code: input.condition,
    severity: input.severity,
    status: "pending",
    version: 1,
    allowed_decisions: input.decisions,
    context: input.context,
    created_at: `${input.created}T02:00:00Z`,
    updated_at: `${input.created}T02:00:00Z`,
  };
}

function importRow(input: {
  id: string;
  account: FinancialAccount | null | undefined;
  status: string;
  adapter: string;
  failure: string | null;
  claims: number;
  date: string;
  periodStart?: string;
  periodEnd?: string;
  dismissed?: boolean;
}): ImportRecord {
  const failed = input.status === "failed";
  return {
    id: input.id,
    source_artifact_id: `${input.id}-artifact`,
    financial_account_id: input.account?.id ?? null,
    financial_account_name: input.account?.display_name ?? null,
    status: input.status,
    adapter_key: input.adapter,
    parser_version: "example-parser-1",
    statement_date: input.periodEnd ?? input.date,
    period_start: input.periodStart ?? null,
    period_end: input.periodEnd ?? null,
    candidate_row_count: input.claims,
    claim_count: input.claims,
    failure_code: input.failure,
    validation_report: {},
    duplicate_arrivals: input.claims === 1284 ? 12 : 0,
    active_review_id: failed ? "example-review-blocking" : null,
    supersedes_extraction_id: null,
    created_at: `${input.date}T01:00:00Z`,
    accepted_at: failed ? null : `${input.date}T03:00:00Z`,
    dismissed_at: input.dismissed ? `${input.date}T04:00:00Z` : null,
  };
}

function series(input: {
  id: string;
  counterparty: string;
  amount: string;
  cadence: RecurringSeries["cadence"];
  interval?: number;
  next: string;
  categoryId: string | null;
  accountId: string | null;
  status: RecurringSeries["status"];
  confidence: string | null;
  linked: number;
  missed?: boolean;
}): RecurringSeries {
  const money = { amount: input.amount, currency: "SGD" };
  return {
    id: input.id,
    counterparty: input.counterparty,
    amount: money,
    amount_min: null,
    amount_max: null,
    cadence: input.cadence,
    interval_days: input.interval ?? null,
    next_expected_date: input.next,
    category_id: input.categoryId,
    primary_account_id: input.accountId,
    status: input.status,
    source: "detected",
    confidence: input.confidence,
    last_matched_tx_id: null,
    last_amount: money,
    linked_count: input.linked,
    missed: input.missed ?? false,
    notes: null,
    cluster_key: input.id,
  };
}

function account(input: {
  id: string;
  slug: string;
  display_name: string;
  institution: string;
  kind: string;
  alias?: string;
}): FinancialAccount {
  return {
    id: input.id,
    slug: input.slug,
    display_name: input.display_name,
    institution: input.institution,
    kind: input.kind,
    default_currency: "SGD",
    statement_adapter_key: "example-statement",
    active: true,
    password_configured: false,
    inbox_ready: true,
    aliases:
      input.alias === undefined
        ? []
        : [
            {
              id: `${input.id}-alias`,
              alias_kind: "apple_wallet_card",
              display_label: input.alias,
            },
          ],
  };
}

function categoryRow(id: string, name: string): Category {
  return { id, name, parent_id: null, active: true };
}

function split(
  category: Category,
  amount: string,
): Transaction["category_splits"][number] {
  return {
    id: `${category.id}-split`,
    name: category.name,
    amount: { amount, currency: "SGD" },
  };
}

function coverage(
  today: Date,
  accounts: FinancialAccount[],
): StatementCoverageReport {
  const month = iso(today).slice(0, 7);
  return {
    as_of: iso(today),
    timezone: "Asia/Singapore",
    window_months: 6,
    accounts: accounts
      .filter((item) => item.kind === "credit_card")
      .map((item) => ({
        id: item.id,
        display_name: item.display_name,
        slug: item.slug,
        months: [
          { month, status: "present" as const },
          { month: shiftMonth(month, -1), status: "missing" as const },
          { month: shiftMonth(month, -2), status: "partial" as const },
        ],
      })),
  };
}

function atLimit(seed: string, limit: number): string {
  const filler = " — Northwind Industries Holdings example ledger";
  let value = seed;
  while (value.length < limit) {
    value += filler;
  }
  return value.slice(0, limit);
}

function iso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shift(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(date.getDate() + days);
  return next;
}

function shiftMonth(yearMonth: string, delta: number): string {
  const [yearText, monthText] = yearMonth.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const date = new Date(year, month - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
