import type { Review, Transaction } from "../api";
import {
  categorizationAmount,
  categorizationCounterparty,
  reviewTransactionId,
  transactionForReview,
} from "./workspace";
import { merchantKey } from "./merchantKey";

export type MerchantGroupMember = {
  reviewId: string;
  transactionId: string;
  version: number;
  counterparty: string;
  amount: string;
  currency: string;
  effectiveDate: string;
};

export type MerchantGroupView = {
  normalizedKey: string;
  label: string;
  etag: string;
  suggestionConfidence: number | null;
  members: MerchantGroupMember[];
};

export const HIGH_JEV_CONFIDENCE = 0.9;

export function remembersByDefault(confidence: number | null): boolean {
  return confidence !== null && confidence >= HIGH_JEV_CONFIDENCE;
}

export function merchantGroupsFromReviews(
  reviews: Review[],
  transactions: Transaction[],
): MerchantGroupView[] {
  const grouped = new Map<string, MerchantGroupMember[]>();
  const confidence = new Map<string, number>();
  for (const review of reviews) {
    if (
      review.condition_code !== "categorization_needed" ||
      review.status !== "pending"
    ) {
      continue;
    }
    const transaction = transactionForReview(review, transactions);
    const transactionId = reviewTransactionId(review);
    if (transactionId === null) {
      continue;
    }
    const counterparty =
      transaction?.counterparty ||
      categorizationCounterparty(review.context) ||
      "";
    const key = merchantKey(counterparty);
    if (key === "") {
      continue;
    }
    const money =
      transaction === undefined
        ? categorizationAmount(review.context)
        : {
            amount: transaction.posted_amount.amount,
            currency: transaction.posted_amount.currency,
          };
    const member: MerchantGroupMember = {
      reviewId: review.id,
      transactionId,
      version: transaction?.version ?? 1,
      counterparty,
      amount: money?.amount ?? "",
      currency: money?.currency ?? "",
      effectiveDate:
        transaction?.effective_date ??
        (typeof review.context.effective_date === "string"
          ? review.context.effective_date
          : ""),
    };
    const current = grouped.get(key) ?? [];
    current.push(member);
    grouped.set(key, current);
    const score = jevConfidence(review);
    if (score !== null) {
      confidence.set(key, Math.max(confidence.get(key) ?? 0, score));
    }
  }
  const groups: MerchantGroupView[] = [];
  for (const [normalizedKey, members] of grouped) {
    if (members.length < 2) {
      continue;
    }
    const ordered = [...members].sort((left, right) =>
      left.effectiveDate.localeCompare(right.effectiveDate),
    );
    groups.push({
      normalizedKey,
      label: groupLabel(ordered.map((member) => member.counterparty)),
      etag: `fixture:${normalizedKey}:${ordered.map((member) => member.transactionId).join("|")}`,
      suggestionConfidence: confidence.get(normalizedKey) ?? null,
      members: ordered,
    });
  }
  groups.sort(
    (left, right) =>
      right.members.length - left.members.length ||
      left.label.localeCompare(right.label),
  );
  return groups;
}

export function maxJevConfidence(reviews: Review[]): number | null {
  let best: number | null = null;
  for (const review of reviews) {
    const score = jevConfidence(review);
    if (score === null) {
      continue;
    }
    best = Math.max(best ?? 0, score);
  }
  return best;
}

function jevConfidence(review: Review): number | null {
  const attempt = review.context.jev_attempt;
  if (typeof attempt !== "object" || attempt === null) {
    return null;
  }
  const raw = (attempt as { choice_confidence?: unknown }).choice_confidence;
  if (typeof raw !== "string" && typeof raw !== "number") {
    return null;
  }
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function groupLabel(counterparties: string[]): string {
  const counts = new Map<string, number>();
  for (const counterparty of counterparties) {
    counts.set(counterparty, (counts.get(counterparty) ?? 0) + 1);
  }
  return (
    [...counts.keys()].sort((left, right) => {
      const byCount = (counts.get(right) ?? 0) - (counts.get(left) ?? 0);
      if (byCount !== 0) {
        return byCount;
      }
      if (left.length !== right.length) {
        return left.length - right.length;
      }
      return left.localeCompare(right);
    })[0] ?? ""
  );
}
