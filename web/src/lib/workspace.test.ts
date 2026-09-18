import { describe, expect, it } from "vitest";

import type { Transaction } from "../api";
import {
  activityAmount,
  categoryTotalsForMonths,
  isProvisional,
  jevAttemptFromContext,
  monthTotals,
  monthlySpending,
  weekComparison,
} from "./workspace";

const card = {
  id: "00000000-0000-0000-0000-000000000011",
  name: "Synthetic Card",
};

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
