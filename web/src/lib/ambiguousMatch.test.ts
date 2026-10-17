import { describe, expect, it } from "vitest";

import { matchReviewView, ordinal, periodLabel } from "./ambiguousMatch";

const provisional = {
  claim_id: "example-claim-wallet",
  counterparty: { raw: "Blue Bottle", normalized: "blue bottle" },
  amount: "8.00",
  currency: "SGD",
  occurred_at: {
    date: "2026-10-10",
    time: "09:41:00",
    timezone: "Asia/Singapore",
  },
  last4: "4242",
  source: "wallet",
  card_alias: "DBS Altitude",
};

function candidate(
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    statement_claim_id: "example-claim-line",
    claim_id: "example-claim-line",
    score: 80,
    reasons: [],
    raw_description: "BLUE BOTTLE COFFEE",
    normalized_counterparty: "blue bottle",
    amount: "8.00",
    currency: "SGD",
    posted_date: "2026-10-11",
    transaction_date: "2026-10-11",
    last4: "4242",
    statement_id: "example-statement-line",
    statement_identity: "dbs:2026-10-31:exampledigest",
    statement_label: "DBS WW",
    issuer: "dbs",
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    amount_delta: "0.00",
    day_delta: 1,
    match_reasons: [],
    ...patch,
  };
}

function view(candidates: Record<string, unknown>[]) {
  return matchReviewView({
    candidate_count: candidates.length,
    provisional,
    candidates,
  });
}

describe("matchReviewView", () => {
  it("ignores a review that has no provisional side", () => {
    expect(matchReviewView({ candidates: [] })).toBeNull();
    expect(matchReviewView({})).toBeNull();
  });

  it("explains a date-only difference and ranks without a percentage", () => {
    const model = view([
      candidate({ statement_claim_id: "later", score: 60, day_delta: 2 }),
      candidate({
        statement_claim_id: "sooner",
        score: 90,
        posted_date: "2026-10-11",
        day_delta: 1,
      }),
    ]);
    expect(model?.subline).toBe(
      "Apple Wallet charge matched 2 statement lines",
    );
    expect(model?.anchor.merchant).toBe("Blue Bottle");
    expect(model?.anchor.when).toBe("10 Oct · 09:41");
    expect(model?.anchor.card).toBe("DBS Altitude · 4242");
    expect(model?.anchor.meta).toBe(
      "10 Oct · 09:41 · DBS Altitude ·· 4242 · Wallet",
    );
    expect(model?.anchor.source).toBe("Wallet");
    expect(model?.candidates.map((item) => item.rankLabel)).toEqual([
      "1st",
      "2nd",
    ]);
    expect(model?.candidates[0]?.why).toBe(
      "Exact amount · 1 day later · Same card",
    );
    expect(model?.candidates[0]?.dateDelta).toBe("+1 day");
    expect(model?.candidates[0]?.merchantMatches).toBe(true);
    expect(model?.candidates[0]?.raw).toBeNull();
    expect(model?.candidates[0]?.best).toBe(true);
    expect(model?.candidates[1]?.best).toBe(false);
    expect(model?.primaryId).toBe("sooner");
    expect(model?.noneLabel).toBe("None of these");
  });

  it("shows an amount delta before the day, including a currency change", () => {
    const model = view([
      candidate({
        statement_claim_id: "tip",
        amount: "8.40",
        amount_delta: "0.40",
        day_delta: 0,
        posted_date: "2026-10-10",
      }),
      candidate({
        statement_claim_id: "fx",
        score: 10,
        amount: "6.20",
        currency: "USD",
        amount_delta: null,
        day_delta: 0,
        posted_date: "2026-10-10",
      }),
    ]);
    expect(model?.candidates[0]?.why.startsWith("SGD 0.40 more")).toBe(true);
    expect(model?.candidates[0]?.amountDelta).toBe("+SGD 0.40");
    expect(model?.candidates[0]?.amountMatches).toBe(false);
    expect(model?.candidates[1]?.why.startsWith("Different currency")).toBe(
      true,
    );
    expect(model?.candidates[1]?.amountDelta).toBe("different currency");
  });

  it("keeps the raw statement descriptor when the merchant differs", () => {
    const model = view([
      candidate({
        raw_description: "APPLE PAY *SQ BLUEBOTTLE 8842",
        normalized_counterparty: "apple pay sq bluebottle",
        day_delta: 0,
        posted_date: "2026-10-10",
        transaction_date: "2026-10-09",
      }),
    ]);
    const line = model?.candidates[0];
    expect(line?.merchant).toBe("Apple Pay Sq Bluebottle");
    expect(line?.raw).toBe("APPLE PAY *SQ BLUEBOTTLE 8842");
    expect(line?.merchantDelta).toBe("merchant differs");
    expect(line?.txn).toBe("txn 9 Oct");
    expect(model?.single).toBe(true);
    expect(model?.noneLabel).toBe("Not this one");
    expect(line?.best).toBe(false);
    expect(line?.statement).toBe("DBS WW · 1–31 Oct");
  });

  it("disables a line already matched to another charge", () => {
    const model = view([
      candidate({ statement_claim_id: "open", score: 80 }),
      candidate({
        statement_claim_id: "used",
        score: 70,
        matched_to: "Blue Bottle Raffles",
      }),
    ]);
    expect(model?.primaryId).toBe("open");
    expect(model?.candidates[1]?.disabled).toBe(true);
    expect(model?.candidates[1]?.matchedTo).toBe("Blue Bottle Raffles");
  });

  it("hides ids and the statement digest from the comparison fields", () => {
    const model = view([candidate()]);
    const line = model?.candidates[0];
    const visible = [
      model?.subline,
      model?.anchor.merchant,
      model?.anchor.amount,
      model?.anchor.card,
      line?.merchant,
      line?.why,
      line?.statement,
      line?.card,
    ].join(" ");
    expect(visible).not.toContain("example-claim");
    expect(visible).not.toContain("exampledigest");
    expect(line?.details.map((detail) => detail.value).join(" ")).toContain(
      "exampledigest",
    );
  });

  it("describes an empty candidate list", () => {
    const model = view([]);
    expect(model?.empty).toBe(true);
    expect(model?.subline).toBe("");
    expect(model?.primaryId).toBeNull();
  });
});

describe("period and rank labels", () => {
  it("formats a same-month period and ordinals", () => {
    expect(periodLabel("2026-10-01", "2026-10-31")).toBe("1–31 Oct");
    expect(periodLabel("2026-12-30", "2027-01-02")).toBe("30 Dec – 2 Jan");
    expect(ordinal(1)).toBe("1st");
    expect(ordinal(2)).toBe("2nd");
    expect(ordinal(3)).toBe("3rd");
    expect(ordinal(11)).toBe("11th");
  });
});
