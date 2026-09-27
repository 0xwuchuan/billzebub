import { describe, expect, it } from "vitest";

import type { Transaction } from "../api";
import type { Review } from "../api";
import {
  activityAmount,
  categorizationAmount,
  categorizationCounterparty,
  categoryTotals,
  categoryTotalsForMonths,
  filterSummary,
  groupTransactions,
  isProvisional,
  jevAttemptFromContext,
  monthTotals,
  monthlySpending,
  nextPendingReviewId,
  resolveReviewTransaction,
  transactionForReview,
  transactionFromReviewContext,
  weekComparison,
} from "./workspace";

const card = {
  id: "00000000-0000-0000-0000-000000000011",
  name: "Synthetic Card",
};

function reviewStub(id: string): Review {
  return {
    id,
    subject_type: "transaction",
    subject_id: id,
    condition_code: "categorization_needed",
    severity: "attention",
    status: "pending",
    version: 1,
    allowed_decisions: ["categorize"],
    context: {},
    created_at: "2026-01-10T00:00:00+00:00",
    updated_at: "2026-01-10T00:00:00+00:00",
  };
}

function transaction(input: {
  id: string;
  kind: string;
  posted: string;
  authorized?: string | null;
  date?: string;
  counterparty?: string;
}): Transaction {
  return {
    id: input.id,
    version: 1,
    financial_account: card,
    counterparty: input.counterparty ?? "Synthetic Counterparty",
    posted_amount: { amount: input.posted, currency: "SGD" },
    authorized_amount:
      input.authorized === undefined || input.authorized === null
        ? null
        : { amount: input.authorized, currency: "SGD" },
    effective_date: input.date ?? "2026-03-07",
    kind: input.kind,
    category_splits: [],
    reviews: [],
  };
}

describe("owner activity amounts", () => {
  it("treats authorized Real-time Claims as provisional until a Posted Amount exists", () => {
    const provisional = transaction({
      id: "00000000-0000-0000-0000-000000000021",
      kind: "expense",
      posted: "0",
      authorized: "-12.34",
    });
    const confirmed = transaction({
      id: "00000000-0000-0000-0000-000000000022",
      kind: "expense",
      posted: "-12.34",
      authorized: "-12.34",
    });
    expect(isProvisional(provisional)).toBe(true);
    expect(activityAmount(provisional)).toEqual({
      amount: "-12.34",
      currency: "SGD",
    });
    expect(isProvisional(confirmed)).toBe(false);
    expect(activityAmount(confirmed)).toEqual({
      amount: "-12.34",
      currency: "SGD",
    });
  });

  it("counts provisional spend from Authorized Amount and excludes Transfers and Income", () => {
    const totals = monthTotals(
      [
        transaction({
          id: "00000000-0000-0000-0000-000000000031",
          kind: "expense",
          posted: "0",
          authorized: "-12.34",
        }),
        transaction({
          id: "00000000-0000-0000-0000-000000000032",
          kind: "expense",
          posted: "-45.67",
        }),
        transaction({
          id: "00000000-0000-0000-0000-000000000033",
          kind: "transfer",
          posted: "0",
          authorized: "-20.00",
        }),
        transaction({
          id: "00000000-0000-0000-0000-000000000034",
          kind: "income",
          posted: "90.00",
        }),
      ],
      "2026-03",
    );
    expect(totals.provisionalCents).toBe(1234);
    expect(totals.confirmedCents).toBe(4567);
    expect(totals.estimatedCents).toBe(5801);
    expect(totals.provisionalCount).toBe(1);
    expect(totals.confirmedCount).toBe(1);
  });

  it("does not double-count a Real-time Claim after Statement confirmation", () => {
    const totals = monthTotals(
      [
        transaction({
          id: "00000000-0000-0000-0000-000000000041",
          kind: "expense",
          posted: "-12.34",
          authorized: "-12.34",
        }),
      ],
      "2026-03",
    );
    expect(totals.confirmedCents).toBe(1234);
    expect(totals.provisionalCents).toBe(0);
    expect(totals.estimatedCents).toBe(1234);
  });

  it("separates confirmed and provisional spending in the current week", () => {
    const comparison = weekComparison(
      [
        transaction({
          id: "00000000-0000-0000-0000-000000000051",
          kind: "expense",
          posted: "-45.67",
          date: "2026-03-11",
        }),
        transaction({
          id: "00000000-0000-0000-0000-000000000052",
          kind: "expense",
          posted: "0",
          authorized: "-12.34",
          date: "2026-03-11",
        }),
      ],
      new Date(2026, 2, 11),
    );

    expect(comparison[2]).toEqual({
      label: "Wed",
      confirmedCents: 4567,
      provisionalCents: 1234,
    });
  });

  it("builds chronological monthly totals and confirmed category allocation", () => {
    const groceries = transaction({
      id: "00000000-0000-0000-0000-000000000061",
      kind: "expense",
      posted: "-45.67",
      date: "2026-01-12",
    });
    groceries.category_splits = [
      {
        id: "00000000-0000-0000-0000-000000000071",
        name: "Groceries",
        amount: { amount: "-45.67", currency: "SGD" },
      },
    ];
    const provisional = transaction({
      id: "00000000-0000-0000-0000-000000000062",
      kind: "expense",
      posted: "0",
      authorized: "-12.34",
      date: "2026-03-07",
    });

    expect(
      monthlySpending([groceries, provisional], new Date(2026, 2, 11), 3).map(
        ({ month, confirmedCents, provisionalCents }) => ({
          month,
          confirmedCents,
          provisionalCents,
        }),
      ),
    ).toEqual([
      { month: "2026-01", confirmedCents: 4567, provisionalCents: 0 },
      { month: "2026-02", confirmedCents: 0, provisionalCents: 0 },
      { month: "2026-03", confirmedCents: 0, provisionalCents: 1234 },
    ]);
    expect(
      categoryTotalsForMonths(
        [groceries, provisional],
        ["2026-01", "2026-02", "2026-03"],
      ),
    ).toEqual([{ name: "Groceries", cents: 4567 }]);
  });

  it("counts categorized provisional spend in the open month", () => {
    const confirmed = transaction({
      id: "00000000-0000-0000-0000-000000000081",
      kind: "expense",
      posted: "-45.67",
      date: "2026-03-02",
    });
    confirmed.category_splits = [
      {
        id: "00000000-0000-0000-0000-000000000091",
        name: "Groceries",
        amount: { amount: "45.67", currency: "SGD" },
      },
    ];
    const categorized = transaction({
      id: "00000000-0000-0000-0000-000000000082",
      kind: "expense",
      posted: "0",
      authorized: "-12.34",
      date: "2026-03-07",
    });
    categorized.category_splits = [
      {
        id: "00000000-0000-0000-0000-000000000092",
        name: "Dining",
        amount: { amount: "12.34", currency: "SGD" },
      },
    ];
    const uncategorized = transaction({
      id: "00000000-0000-0000-0000-000000000083",
      kind: "expense",
      posted: "0",
      authorized: "-3.00",
      date: "2026-03-08",
    });
    const priorMonth = transaction({
      id: "00000000-0000-0000-0000-000000000084",
      kind: "expense",
      posted: "0",
      authorized: "-9.00",
      date: "2026-02-08",
    });
    priorMonth.category_splits = [
      {
        id: "00000000-0000-0000-0000-000000000093",
        name: "Dining",
        amount: { amount: "9.00", currency: "SGD" },
      },
    ];

    const rows = [confirmed, categorized, uncategorized, priorMonth];
    const totals = monthTotals(rows, "2026-03");
    expect(totals.confirmedCents).toBe(4567);
    expect(totals.provisionalCents).toBe(1534);
    expect(totals.estimatedCents).toBe(6101);
    expect(categoryTotals(rows, "2026-03")).toEqual([
      { name: "Groceries", cents: 4567 },
      { name: "Dining", cents: 1234 },
    ]);
  });
});

describe("nextPendingReviewId", () => {
  it("advances to the next Pending Review and clears after the last", () => {
    const first = reviewStub("00000000-0000-0000-0000-000000000101");
    const second = reviewStub("00000000-0000-0000-0000-000000000102");
    expect(nextPendingReviewId([first, second], first.id)).toBe(second.id);
    expect(nextPendingReviewId([first, second], second.id)).toBe("");
    expect(nextPendingReviewId([], first.id)).toBe("");
  });
});

describe("review Transaction join and context fallthrough", () => {
  it("joins a categorization Review to the matching Transaction", () => {
    const listed = transaction({
      id: "00000000-0000-0000-0000-000000000201",
      kind: "expense",
      posted: "-12.34",
      counterparty: "Synthetic Coffee",
    });
    const review = reviewStub(listed.id);
    expect(transactionForReview(review, [listed])).toEqual(listed);
    expect(resolveReviewTransaction(review, [listed])).toEqual(listed);
  });

  it("rebuilds Counterparty and amount from Review context when the list misses", () => {
    const review = {
      ...reviewStub("00000000-0000-0000-0000-000000000202"),
      context: {
        transaction_id: "00000000-0000-0000-0000-000000000202",
        counterparty: "Synthetic Orphan Cafe",
        amount: "-18.50",
        currency: "SGD",
        account: "Synthetic Card",
        effective_date: "2026-01-10",
        version: 3,
      },
    };
    expect(transactionForReview(review, [])).toBeUndefined();
    expect(categorizationCounterparty(review.context)).toBe(
      "Synthetic Orphan Cafe",
    );
    expect(categorizationAmount(review.context)).toEqual({
      amount: "-18.50",
      currency: "SGD",
    });
    const resolved = transactionFromReviewContext(review);
    expect(resolved?.id).toBe(review.subject_id);
    expect(resolved?.counterparty).toBe("Synthetic Orphan Cafe");
    expect(resolved?.posted_amount).toEqual({
      amount: "-18.50",
      currency: "SGD",
    });
    expect(resolved?.version).toBe(3);
    expect(resolveReviewTransaction(review, [])).toEqual(resolved);
  });
});

describe("transaction list grouping and totals", () => {
  it("groups consecutive dates with Today and weekday labels", () => {
    const today = new Date(2026, 0, 12);
    const groups = groupTransactions(
      [
        transaction({
          id: "00000000-0000-0000-0000-000000000301",
          kind: "expense",
          posted: "-12.00",
          date: "2026-01-12",
        }),
        transaction({
          id: "00000000-0000-0000-0000-000000000302",
          kind: "expense",
          posted: "-8.00",
          date: "2026-01-10",
        }),
      ],
      today,
    );
    expect(groups.map((group) => group.key)).toEqual([
      "Today",
      "Saturday, January 10",
    ]);
    expect(groups[0]?.rows).toHaveLength(1);
  });

  it("summarizes spent, income, and net from filtered rows without inventing streams", () => {
    const summary = filterSummary([
      transaction({
        id: "00000000-0000-0000-0000-000000000311",
        kind: "expense",
        posted: "-12.34",
      }),
      transaction({
        id: "00000000-0000-0000-0000-000000000312",
        kind: "income",
        posted: "40.00",
      }),
      transaction({
        id: "00000000-0000-0000-0000-000000000313",
        kind: "transfer",
        posted: "-20.00",
      }),
    ]);
    expect(summary).toEqual({
      count: 3,
      spentCents: 1234,
      incomeCents: 4000,
      netCents: 1234 - 4000,
      currency: "SGD",
    });
  });
});

describe("jevAttemptFromContext", () => {
  it("reads the last Jev skip from Review context", () => {
    expect(jevAttemptFromContext({})).toBeNull();
    expect(
      jevAttemptFromContext({
        jev_attempt: {
          action: "skip",
          model: "jev-1.13.0",
          choice: "Synthetic Food",
          choice_confidence: "0.49",
          noul: "0.40",
          category_name: null,
          error_class: null,
          error_message: null,
        },
      }),
    ).toEqual({
      attempted_at: "",
      model: "jev-1.13.0",
      action: "skip",
      choice: "Synthetic Food",
      choice_confidence: "0.49",
      noul: "0.40",
      category_id: null,
      category_name: null,
      error_class: null,
      error_message: null,
    });
  });
});
