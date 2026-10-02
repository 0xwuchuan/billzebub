import { describe, expect, it } from "vitest";

import type { RecurringSeries } from "../api";
import {
  cadenceLabel,
  confidenceLabel,
  dueGroups,
  recurringAmountLabel,
  relativeDueLabel,
} from "./recurrings";

const today = new Date(2026, 8, 15);

function series(
  id: string,
  counterparty: string,
  next: string,
): RecurringSeries {
  return {
    id,
    counterparty,
    amount: { amount: "10.00", currency: "SGD" },
    amount_min: null,
    amount_max: null,
    cadence: "monthly",
    interval_days: null,
    next_expected_date: next,
    category_id: null,
    primary_account_id: null,
    status: "active",
    source: "detected",
    confidence: "0.91",
    last_matched_tx_id: null,
    last_amount: { amount: "10.00", currency: "SGD" },
    linked_count: 1,
    missed: false,
    notes: null,
    cluster_key: id,
  };
}

describe("recurring labels", () => {
  it("names cadence, confidence, amount, and relative due dates", () => {
    expect(cadenceLabel("weekly", null)).toBe("Weekly");
    expect(cadenceLabel("custom_days", 14)).toBe("Every 14 days");
    expect(confidenceLabel("0.91")).toBe("High");
    expect(confidenceLabel("0.62")).toBe("Med");
    expect(confidenceLabel("0.2")).toBe("Low");
    expect(confidenceLabel(null)).toBeNull();
    expect(recurringAmountLabel({ amount: "16.98", currency: "SGD" })).toBe(
      "−SGD 16.98",
    );
    expect(relativeDueLabel("2026-09-15", today)).toBe("Today");
    expect(relativeDueLabel("2026-09-16", today)).toBe("Tomorrow");
    expect(relativeDueLabel("2026-09-12", today)).toBe("3 days ago");
  });

  it("groups soonest dues first, then later", () => {
    const groups = dueGroups(
      [
        series("later", "Later Co", "2026-10-01"),
        series("soon", "Soon Co", "2026-09-18"),
        series("overdue", "Overdue Co", "2026-09-10"),
      ],
      today,
    );
    expect(groups.map((group) => group.label)).toEqual([
      "Due this week",
      "Later",
    ]);
    expect(groups[0]?.items.map((item) => item.counterparty)).toEqual([
      "Overdue Co",
      "Soon Co",
    ]);
    expect(groups[1]?.items.map((item) => item.counterparty)).toEqual([
      "Later Co",
    ]);
  });
});
