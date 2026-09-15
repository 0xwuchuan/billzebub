import { ApiError, type Transaction } from "../api";

export function categoryLabel(transaction: Transaction): string {
  return (
    transaction.category_splits.map((split) => split.name).join(", ") ||
    "Uncategorized"
  );
}

export function kindLabel(kind: string): string {
  return kind
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function reviewTitle(condition: string): string {
  if (condition === "categorization_needed") {
    return "Category needed";
  }
  if (condition === "extraction_failed") {
    return "Failed Extraction";
  }
  if (condition === "apple_wallet_unmapped_card") {
    return "Wallet card unmapped";
  }
  if (condition === "shortcut_payload_invalid") {
    return "Shortcut payload rejected";
  }
  if (condition === "paylah_account_missing") {
    return "PayLah account missing";
  }
  if (condition === "paylah_account_ambiguous") {
    return "PayLah account ambiguous";
  }
  return condition
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function decisionLabel(choice: string): string {
  const known: Record<string, string> = {
    retry: "Retry Extraction",
    retry_after_adapter_update: "Retry Extraction",
    keep_quarantine: "Keep quarantined",
    exclude_source_artifact: "Keep quarantined",
    mark_unconfirmed: "Mark Unconfirmed",
    keep_waiting: "Keep waiting",
    exclude: "Exclude Claim",
    confirm_match: "Confirm match",
    keep_separate: "Keep separate",
    exclude_realtime: "Exclude Real-time Claim",
    configure_card_alias: "Map Wallet card in Settings",
    configure_paylah_account: "Create PayLah account in Settings",
    approve_exact_diff: "Approve reprocess",
    keep_previous_extraction: "Keep previous Extraction",
  };
  return (
    known[choice] ??
    choice
      .replaceAll("_", " ")
      .replace(/\b\w/g, (character) => character.toUpperCase())
  );
}

export function openedLabel(createdAt: string, now: Date): string {
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) {
    return "opened recently";
  }
  const days = Math.max(
    0,
    Math.floor((now.getTime() - created.getTime()) / 86_400_000),
  );
  return `opened ${days} ${days === 1 ? "day" : "days"} ago`;
}

export function dayMonthLabel(isoDate: string): string {
  const parts = isoDate.split("-");
  const day = parts[2];
  const month = parts[1];
  if (day === undefined || month === undefined) {
    return isoDate;
  }
  const names = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const monthIndex = Number(month) - 1;
  return `${Number(day)} ${names[monthIndex] ?? month}`;
}

export function monthYearLabel(isoDate: string): string {
  const parts = isoDate.split("-");
  const year = parts[0];
  const month = parts[1];
  if (year === undefined || month === undefined) {
    return isoDate;
  }
  const names = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];
  const monthIndex = Number(month) - 1;
  return `${names[monthIndex] ?? month} ${year}`;
}

export function shortMonthLabel(yearMonth: string): string {
  return monthYearLabel(`${yearMonth}-01`).slice(0, 3);
}

export function formatOwnerCardLabel(value: string): string {
  const compact = value.trim().replace(/\s+/g, " ");
  if (compact === "") {
    return compact;
  }
  const stripped = compact.replace(/[•*]+/g, " ").replace(/\s+/g, " ").trim();
  const match = /(\d{4})$/.exec(stripped);
  if (match === null || match[1] === undefined) {
    return stripped;
  }
  const last4 = match[1];
  const name = stripped
    .slice(0, match.index)
    .replace(/[\s-]+$/u, "")
    .trim();
  if (name === "") {
    return last4;
  }
  return `${name} • ${last4}`;
}

export function isoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function categoryColor(name: string): string {
  const colors: Record<string, string> = {
    Groceries: "var(--bz-cat-groceries)",
    Dining: "var(--bz-cat-dining)",
    Transport: "var(--bz-cat-transport)",
    Utilities: "var(--bz-cat-utilities)",
    Health: "var(--bz-cat-health)",
    Shopping: "var(--bz-cat-shopping)",
    Gifts: "var(--bz-cat-gifts)",
    Uncategorized: "var(--bz-cat-uncat)",
  };
  return colors[name] ?? "var(--bz-cat-uncat)";
}

export function messageFor(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The local workspace is unavailable. Check the API and refresh.";
}
