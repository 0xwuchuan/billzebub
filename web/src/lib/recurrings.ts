import type { Category, RecurringCadence, RecurringSeries } from "../api";
import { dayMonthLabel, isoDate } from "./labels";
import { formatUnsigned } from "./money";

export function cadenceLabel(
  cadence: RecurringCadence,
  intervalDays: number | null,
): string {
  if (cadence === "weekly") {
    return "Weekly";
  }
  if (cadence === "monthly") {
    return "Monthly";
  }
  if (cadence === "yearly") {
    return "Yearly";
  }
  if (intervalDays !== null && intervalDays > 0) {
    return `Every ${intervalDays} days`;
  }
  return "Custom";
}

export function confidenceLabel(confidence: string | null): string | null {
  if (confidence === null || confidence.trim() === "") {
    return null;
  }
  const value = Number(confidence);
  if (!Number.isFinite(value)) {
    return null;
  }
  if (value >= 0.8) {
    return "High";
  }
  if (value >= 0.5) {
    return "Med";
  }
  return "Low";
}

export function recurringAmountLabel(amount: {
  amount: string;
  currency: string;
}): string {
  return `−${formatUnsigned(amount)}`;
}

export function relativeDueLabel(isoDay: string, today: Date): string {
  const days = dayDistance(isoDay, today);
  if (days === null) {
    return isoDay;
  }
  if (days === 0) {
    return "Today";
  }
  if (days === 1) {
    return "Tomorrow";
  }
  if (days === -1) {
    return "Yesterday";
  }
  if (days > 1 && days < 14) {
    return `in ${days} days`;
  }
  if (days < -1 && days > -14) {
    return `${Math.abs(days)} days ago`;
  }
  return dayMonthLabel(isoDay);
}

export function categoryName(
  categories: Category[],
  categoryId: string | null,
): string | null {
  if (categoryId === null) {
    return null;
  }
  return (
    categories.find((category) => category.id === categoryId)?.name ?? null
  );
}

export type DueGroup = {
  label: "Due this week" | "Later";
  items: RecurringSeries[];
};

export function dueGroups(series: RecurringSeries[], today: Date): DueGroup[] {
  const horizon = isoDate(addDays(today, 6));
  const sorted = [...series].sort((left, right) => {
    const byDate = left.next_expected_date.localeCompare(
      right.next_expected_date,
    );
    if (byDate !== 0) {
      return byDate;
    }
    return left.counterparty.localeCompare(right.counterparty);
  });
  const due = sorted.filter((item) => item.next_expected_date <= horizon);
  const later = sorted.filter((item) => item.next_expected_date > horizon);
  const groups: DueGroup[] = [];
  if (due.length > 0) {
    groups.push({ label: "Due this week", items: due });
  }
  if (later.length > 0) {
    groups.push({ label: "Later", items: later });
  }
  return groups;
}

function dayDistance(isoDay: string, today: Date): number | null {
  const parts = isoDay.split("-");
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (
    !Number.isFinite(year) ||
    !Number.isFinite(month) ||
    !Number.isFinite(day)
  ) {
    return null;
  }
  const target = Date.UTC(year, month - 1, day);
  const start = Date.UTC(
    today.getFullYear(),
    today.getMonth(),
    today.getDate(),
  );
  return Math.round((target - start) / 86_400_000);
}

function addDays(today: Date, days: number): Date {
  const next = new Date(today);
  next.setDate(today.getDate() + days);
  return next;
}
