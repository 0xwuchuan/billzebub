import type { ImportRecord, Money, Review, Transaction } from "../api";
import { dateGroupLabel, isoDate } from "./labels";
import { amountToCents, centsToMoney } from "./money";

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
  date: string;
  rows: Transaction[];
};

export type FilterSummary = {
  count: number;
  spentCents: number;
  incomeCents: number;
  netCents: number;
  currency: string;
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

export function canCategorize(transaction: Transaction): boolean {
  return (
    isExpense(transaction) && confirmationState(transaction) === "confirmed"
  );
}

export function filterSummary(items: Transaction[]): FilterSummary {
  let spentCents = 0;
  let incomeCents = 0;
  const currency = items[0]?.posted_amount.currency ?? "SGD";
  for (const transaction of items) {
    const cents = Math.abs(amountToCents(activityAmount(transaction).amount));
    if (transaction.kind === "income") {
      incomeCents += cents;
      continue;
    }
    if (transaction.kind === "transfer") {
      continue;
    }
    if (transaction.kind === "refund" || transaction.kind === "reimbursement") {
      spentCents -= cents;
      continue;
    }
    spentCents += cents;
  }
  return {
    count: items.length,
    spentCents,
    incomeCents,
    netCents: spentCents - incomeCents,
    currency,
  };
}

export function groupSpentCents(rows: Transaction[]): number {
  return filterSummary(rows).spentCents;
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
    if (isProvisional(transaction) && !hasCatalogCategory(transaction)) {
      continue;
    }
    const name = categoryName(transaction);
    const cents = isProvisional(transaction)
      ? provisionalSpendCents(transaction)
      : Math.abs(amountToCents(transaction.posted_amount.amount));
    map.set(name, (map.get(name) ?? 0) + cents);
  }
  return [...map.entries()]
    .map(([name, cents]) => ({ name, cents }))
    .sort((left, right) => right.cents - left.cents);
}

function hasCatalogCategory(transaction: Transaction): boolean {
  return transaction.category_splits.some(
    (split) => split.name !== "Uncategorized",
  );
}

function provisionalSpendCents(transaction: Transaction): number {
  const authorized = transaction.authorized_amount;
  if (authorized === null) {
    return Math.abs(amountToCents(transaction.posted_amount.amount));
  }
  return Math.abs(amountToCents(authorized.amount));
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
  const groups: TransactionGroup[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last !== undefined && last.date === item.effective_date) {
      last.rows.push(item);
      continue;
    }
    groups.push({
      key: dateGroupLabel(item.effective_date, today),
      date: item.effective_date,
      rows: [item],
    });
  }
  return groups;
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

export function nextPendingReviewId(
  items: Review[],
  currentId: string,
): string {
  const index = items.findIndex((item) => item.id === currentId);
  if (index === -1) {
    return items[0]?.id ?? "";
  }
  return items[index + 1]?.id ?? "";
}

export function transactionForReview(
  review: Review,
  transactions: Transaction[],
): Transaction | undefined {
  const ids = new Set<string>();
  if (
    review.subject_type === "transaction" ||
    review.subject_type === "claim"
  ) {
    ids.add(review.subject_id);
  }
  const contextId = contextString(review.context, "transaction_id");
  if (contextId !== null) {
    ids.add(contextId);
  }
  if (ids.size === 0) {
    return undefined;
  }
  return transactions.find((transaction) => ids.has(transaction.id));
}

export function reviewTransactionId(review: Review): string | null {
  return (
    contextString(review.context, "transaction_id") ??
    (review.subject_type === "transaction" ? review.subject_id : null)
  );
}

export function categorizationCounterparty(
  context: Record<string, unknown>,
): string | null {
  return (
    contextString(context, "counterparty") ??
    contextString(context, "subject") ??
    contextString(context, "raw") ??
    nestedContextString(context, "jev_attempt", "counterparty")
  );
}

export function categorizationAmount(
  context: Record<string, unknown>,
): Money | null {
  return contextMoney(context) ?? nestedContextMoney(context, "jev_attempt");
}

export function transactionFromReviewContext(
  review: Review,
): Transaction | undefined {
  const id = reviewTransactionId(review);
  if (id === null) {
    return undefined;
  }
  const amount = categorizationAmount(review.context);
  return {
    id,
    version: contextVersion(review.context),
    financial_account: {
      id: contextString(review.context, "financial_account_id") ?? "",
      name: contextString(review.context, "account") ?? "",
    },
    counterparty:
      categorizationCounterparty(review.context) ?? "Unknown Counterparty",
    posted_amount: amount ?? { amount: "0", currency: "SGD" },
    authorized_amount: null,
    effective_date: contextString(review.context, "effective_date") ?? "",
    kind: contextString(review.context, "kind") ?? "expense",
    category_splits: [],
    reviews: [],
  };
}

export function resolveReviewTransaction(
  review: Review,
  transactions: Transaction[],
): Transaction | undefined {
  return (
    transactionForReview(review, transactions) ??
    transactionFromReviewContext(review)
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
  return typeof value === "string" && value !== "" ? value : null;
}

function contextVersion(context: Record<string, unknown>): number {
  const value = context.version;
  if (typeof value === "number" && Number.isInteger(value) && value >= 1) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isInteger(parsed) && parsed >= 1) {
      return parsed;
    }
  }
  return 1;
}

function contextMoney(context: Record<string, unknown>): Money | null {
  const amount = context.amount;
  const currency = context.currency;
  if (typeof amount === "string" && typeof currency === "string") {
    return { amount, currency };
  }
  if (amount !== null && typeof amount === "object" && !Array.isArray(amount)) {
    const record = amount as Record<string, unknown>;
    if (
      typeof record.amount === "string" &&
      typeof record.currency === "string"
    ) {
      return { amount: record.amount, currency: record.currency };
    }
  }
  return null;
}

function nestedContext(
  context: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = context[key];
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function nestedContextString(
  context: Record<string, unknown>,
  key: string,
  field: string,
): string | null {
  const nested = nestedContext(context, key);
  return nested === null ? null : contextString(nested, field);
}

function nestedContextMoney(
  context: Record<string, unknown>,
  key: string,
): Money | null {
  const nested = nestedContext(context, key);
  return nested === null ? null : contextMoney(nested);
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

export type JevAttempt = {
  attempted_at: string;
  model: string;
  action: string;
  choice: string | null;
  choice_confidence: string | null;
  noul: string | null;
  category_id: string | null;
  category_name: string | null;
  error_class: string | null;
  error_message: string | null;
};

export function jevAttemptFromContext(
  context: Record<string, unknown>,
): JevAttempt | null {
  const value = context.jev_attempt;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (typeof record.action !== "string" || typeof record.model !== "string") {
    return null;
  }
  return {
    attempted_at: stringField(record.attempted_at),
    model: record.model,
    action: record.action,
    choice: nullableString(record.choice),
    choice_confidence: nullableString(record.choice_confidence),
    noul: nullableString(record.noul),
    category_id: nullableString(record.category_id),
    category_name: nullableString(record.category_name),
    error_class: nullableString(record.error_class),
    error_message: nullableString(record.error_message),
  };
}

function stringField(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
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
