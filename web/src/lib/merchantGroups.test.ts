import { describe, expect, it } from "vitest";

import type { Review, Transaction } from "../api";
import { merchantKey } from "./merchantKey";
import { merchantGroupsFromReviews } from "./merchantGroups";

describe("merchant groups", () => {
  it("folds noise, digits, and case into one key", () => {
    expect(merchantKey("Example Spotify")).toBe("example spotify");
    expect(merchantKey("Example Spotify SG")).toBe("example spotify");
    expect(merchantKey("Example Spotify 1234")).toBe("example spotify");
    expect(merchantKey("Example Grocer Market Pte Ltd")).toBe(
      "example grocer market",
    );
  });

  it("groups two or more pending categorization reviews and leaves singles out", () => {
    const transactions = [
      charge("spotify-1", "Example Spotify"),
      charge("spotify-2", "Example Spotify SG"),
      charge("cafe", "Example Cafe"),
    ];
    const reviews = transactions.map((transaction) =>
      review(transaction.id, transaction.counterparty),
    );

    const groups = merchantGroupsFromReviews(reviews, transactions);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.label).toBe("Example Spotify");
    expect(groups[0]?.members).toHaveLength(2);
    expect(groups[0]?.normalizedKey).toBe("example spotify");
  });
});

function charge(id: string, counterparty: string): Transaction {
  return {
    id,
    version: 1,
    financial_account: { id: "account", name: "Example Card" },
    counterparty,
    posted_amount: { amount: "-11.98", currency: "SGD" },
    authorized_amount: null,
    effective_date: "2026-08-15",
    kind: "expense",
    category_splits: [],
    reviews: [],
  };
}

function review(transactionId: string, counterparty: string): Review {
  return {
    id: `${transactionId}-review`,
    subject_type: "transaction",
    subject_id: transactionId,
    condition_code: "categorization_needed",
    severity: "attention",
    status: "pending",
    version: 1,
    allowed_decisions: ["assign"],
    context: { transaction_id: transactionId, counterparty },
    created_at: "2026-08-15T00:00:00Z",
    updated_at: "2026-08-15T00:00:00Z",
  };
}
