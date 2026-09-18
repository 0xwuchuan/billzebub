import type { ImportRecord, Review, Transaction } from "../api";
import { amountToCents, centsToMoney } from "./money";
import { isoDate } from "./labels";

export type ConfirmationFilter = "" | "confirmed" | "provisional" | "review";

export type MonthTotals = {
  currency: string;
  confirmedCents: number;
  provisionalCents: number;
  estimatedCents: number;
  confirmedCount: number;
  provisionalCount: number;
};

export type CategoryTotal = {
  name: string;
  cents: number;
};

export type WeekComparison = {
  label: string;
  confirmedCents: number;
  provisionalCents: number;
};

export type MonthlySpending = {
  month: string;
  label: string;
  confirmedCents: number;
  provisionalCents: number;
  estimatedCents: number;
};

export type TransactionGroup = {
  key: string;
  rows: Transaction[];
};

export function isExpense(transaction: Transaction): boolean {
  return transaction.kind === "expense";
}

export function needsCategorization(transaction: Transaction): boolean {
  return transaction.reviews.some(
    (review) => review.condition_code === "categorization_needed",
  );
}

export function isProvisional(transaction: Transaction): boolean {
  return (
    transaction.authorized_amount !== null &&
    amountToCents(transaction.posted_amount.amount) === 0
  );
}

export function activityAmount(
  transaction: Transaction,
): Transaction["posted_amount"] {
  if (isProvisional(transaction) && transaction.authorized_amount !== null) {
    return transaction.authorized_amount;
  }
  return transaction.posted_amount;
}

export function confirmationState(
  transaction: Transaction,
): "confirmed" | "provisional" {
  return isProvisional(transaction) ? "provisional" : "confirmed";
}

export function reportingPeriod(
  _transactions: Transaction[],
  today: Date,
): string {
  return isoDate(today).slice(0, 7);
}

export function inPeriod(transaction: Transaction, yearMonth: string): boolean {
  return transaction.effective_date.startsWith(yearMonth);
}

export function monthTotals(
  transactions: Transaction[],
  yearMonth: string,
): MonthTotals {
  const expenses = transactions.filter(
    (transaction) => isExpense(transaction) && inPeriod(transaction, yearMonth),
  );
  const currency = expenses[0]?.posted_amount.currency ?? "SGD";
  let confirmedCents = 0;
  let provisionalCents = 0;
  let confirmedCount = 0;
  let provisionalCount = 0;
  for (const transaction of expenses) {
    const cents = Math.abs(amountToCents(transaction.posted_amount.amount));
    if (isProvisional(transaction)) {
      const authorized = transaction.authorized_amount;
      provisionalCents +=
        authorized === null
          ? cents
          : Math.abs(amountToCents(authorized.amount));
      provisionalCount += 1;
    } else {
      confirmedCents += cents;
      confirmedCount += 1;
    }
  }
  return {
    currency,
    confirmedCents,
    provisionalCents,
    estimatedCents: confirmedCents + provisionalCents,
    confirmedCount,
    provisionalCount,
  };
}

export function categoryTotals(
  transactions: Transaction[],
  yearMonth: string,
): CategoryTotal[] {
  const map = new Map<string, number>();
  for (const transaction of transactions) {
    if (!isExpense(transaction) || !inPeriod(transaction, yearMonth)) {
      continue;
    }
    if (isProvisional(transaction)) {
      continue;
    }
    const name =
      transaction.category_splits.map((split) => split.name).join(", ") ||
      "Uncategorized";
    const cents = Math.abs(amountToCents(transaction.posted_amount.amount));
    map.set(name, (map.get(name) ?? 0) + cents);
  }
  return [...map.entries()]
    .map(([name, cents]) => ({ name, cents }))
    .sort((left, right) => right.cents - left.cents);
}

export function weekComparison(
  transactions: Transaction[],
  today: Date,
): WeekComparison[] {
  const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const monday = startOfWeek(today);
  return labels.map((label, index) => {
    const day = new Date(monday);
    day.setDate(monday.getDate() + index);
    const key = isoDate(day);
    let confirmedCents = 0;
    let provisionalCents = 0;
    for (const transaction of transactions) {
      if (!isExpense(transaction) || transaction.effective_date !== key) {
        continue;
      }
      const cents = Math.abs(amountToCents(activityAmount(transaction).amount));
      if (isProvisional(transaction)) {
        provisionalCents += cents;
      } else {
        confirmedCents += cents;
      }
    }
    return { label, confirmedCents, provisionalCents };
  });
}

export function monthlySpending(
  transactions: Transaction[],
  today: Date,
  count = 6,
): MonthlySpending[] {
  return Array.from({ length: count }, (_, index) => {
    const offset = index - count + 1;
    const monthDate = new Date(
      today.getFullYear(),
      today.getMonth() + offset,
      1,
    );
    const month = `${monthDate.getFullYear()}-${String(monthDate.getMonth() + 1).padStart(2, "0")}`;
    const totals = monthTotals(transactions, month);
    return {
      month,
      label: monthDate.toLocaleString("en-SG", { month: "short" }),
      confirmedCents: totals.confirmedCents,
      provisionalCents: totals.provisionalCents,
      estimatedCents: totals.estimatedCents,
    };
  });
}

export function categoryTotalsForMonths(
  transactions: Transaction[],
  months: readonly string[],
): CategoryTotal[] {
  const included = new Set(months);
  const map = new Map<string, number>();
  for (const transaction of transactions) {
    if (
      !isExpense(transaction) ||
      isProvisional(transaction) ||
      !included.has(transaction.effective_date.slice(0, 7))
    ) {
      continue;
    }
    const name = categoryName(transaction);
    const cents = Math.abs(amountToCents(transaction.posted_amount.amount));
    map.set(name, (map.get(name) ?? 0) + cents);
  }
  return [...map.entries()]
    .map(([name, cents]) => ({ name, cents }))
    .sort((left, right) => right.cents - left.cents);
}

export function filterTransactions(input: {
  items: Transaction[];
  query: string;
  accountId: string;
  category: string;
  confirmation: ConfirmationFilter;
}): Transaction[] {
  const query = input.query.trim().toLowerCase();
  return input.items.filter((transaction) => {
    if (
      input.accountId !== "" &&
      transaction.financial_account.id !== input.accountId &&
      transaction.financial_account.name !== input.accountId
    ) {
      return false;
    }
    const category = categoryName(transaction);
    if (input.category !== "" && category !== input.category) {
      return false;
    }
    const state = confirmationState(transaction);
    if (input.confirmation === "confirmed" && state !== "confirmed") {
      return false;
    }
    if (input.confirmation === "provisional" && state !== "provisional") {
      return false;
    }
    if (input.confirmation === "review" && !needsCategorization(transaction)) {
      return false;
    }
    if (query !== "") {
      const hay = [
        transaction.counterparty,
        transaction.financial_account.name,
        category,
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(query)) {
        return false;
      }
    }
    return true;
  });
}

export function groupTransactions(
  items: Transaction[],
  today: Date,
): TransactionGroup[] {
  const todayKey = isoDate(today);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const yesterdayKey = isoDate(yesterday);
  const weekStart = isoDate(startOfWeek(today));
  const buckets: TransactionGroup[] = [
    { key: "Today", rows: [] },
    { key: "Yesterday", rows: [] },
    { key: "This week", rows: [] },
    { key: `Earlier in ${monthName(today)}`, rows: [] },
  ];
  const todayBucket = buckets[0];
  const yesterdayBucket = buckets[1];
  const weekBucket = buckets[2];
  const earlierBucket = buckets[3];
  if (
    todayBucket === undefined ||
    yesterdayBucket === undefined ||
    weekBucket === undefined ||
    earlierBucket === undefined
  ) {
    return [];
  }
  for (const item of items) {
    if (item.effective_date === todayKey) {
      todayBucket.rows.push(item);
    } else if (item.effective_date === yesterdayKey) {
      yesterdayBucket.rows.push(item);
    } else if (
      item.effective_date >= weekStart &&
      item.effective_date < todayKey
    ) {
      weekBucket.rows.push(item);
    } else {
      earlierBucket.rows.push(item);
    }
  }
  return buckets.filter((bucket) => bucket.rows.length > 0);
}

export function sortTransactions(items: Transaction[]): Transaction[] {
  return [...items].sort((left, right) => {
    if (left.effective_date !== right.effective_date) {
      return left.effective_date < right.effective_date ? 1 : -1;
    }
    return (
      Math.abs(amountToCents(activityAmount(right).amount)) -
      Math.abs(amountToCents(activityAmount(left).amount))
    );
  });
}

export function sortReviews(reviews: Review[]): Review[] {
  return [...reviews].sort((left, right) => {
    if (left.severity !== right.severity) {
      return left.severity === "blocking" ? -1 : 1;
    }
    return left.created_at < right.created_at ? -1 : 1;
  });
}

export function filterReviews(
  reviews: Review[],
  filter: "" | "blocking" | "attention",
): Review[] {
  return sortReviews(
    reviews.filter((review) => {
      if (filter === "blocking") {
        return review.severity === "blocking";
      }
      if (filter === "attention") {
        return review.severity === "attention";
      }
      return true;
    }),
  );
}

export function transactionForReview(
  review: Review,
  transactions: Transaction[],
): Transaction | undefined {
  if (
    review.subject_type !== "transaction" &&
    review.subject_type !== "claim"
  ) {
    return undefined;
  }
  return transactions.find(
    (transaction) => transaction.id === review.subject_id,
  );
}

export function importForReview(
  review: Review,
  imports: ImportRecord[],
): ImportRecord | undefined {
  if (review.subject_type === "extraction") {
    return imports.find((item) => item.id === review.subject_id);
  }
  if (review.subject_type === "source_artifact") {
    return imports.find(
      (item) => item.source_artifact_id === review.subject_id,
    );
  }
  return undefined;
}

export function contextString(
  context: Record<string, unknown>,
  key: string,
): string | null {
  const value = context[key];
  return typeof value === "string" ? value : null;
}

export function contextStrings(
  context: Record<string, unknown>,
  key: string,
): string[] {
  const value = context[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

export function moneyFromCents(cents: number, currency: string) {
  return centsToMoney(cents, currency);
}

function categoryName(transaction: Transaction): string {
  return (
    transaction.category_splits.map((split) => split.name).join(", ") ||
    "Uncategorized"
  );
}

function startOfWeek(today: Date): Date {
  const date = new Date(today);
  const day = date.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  date.setDate(date.getDate() + mondayOffset);
  return date;
}

function monthName(today: Date): string {
  return today.toLocaleString("en-SG", { month: "long" });
}
