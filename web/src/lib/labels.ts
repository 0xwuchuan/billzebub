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

export function dateGroupLabel(isoDay: string, today: Date): string {
  const todayKey = isoDate(today);
  if (isoDay === todayKey) {
    return "Today";
  }
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (isoDay === isoDate(yesterday)) {
    return "Yesterday";
  }
  const parts = isoDay.split("-");
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (
    !Number.isFinite(year) ||
    !Number.isFinite(month) ||
    !Number.isFinite(day)
  ) {
    return isoDay;
  }
  const date = new Date(year, month - 1, day);
  const weekday = date.toLocaleDateString("en-US", { weekday: "long" });
  const monthName = date.toLocaleDateString("en-US", { month: "long" });
  if (year !== today.getFullYear()) {
    return `${weekday}, ${monthName} ${day}, ${year}`;
  }
  return `${weekday}, ${monthName} ${day}`;
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

const NAMED_CATEGORY_COLORS: Record<string, string> = {
  Groceries: "var(--bz-cat-groceries)",
  Dining: "var(--bz-cat-dining)",
  Transport: "var(--bz-cat-transport)",
  Utilities: "var(--bz-cat-utilities)",
  Health: "var(--bz-cat-health)",
  Shopping: "var(--bz-cat-shopping)",
  Gifts: "var(--bz-cat-gifts)",
  Uncategorized: "var(--bz-cat-uncat)",
};

const CATEGORY_HUES = [
  "var(--bz-hue-cyan)",
  "var(--bz-hue-orange)",
  "var(--bz-hue-blue)",
  "var(--bz-hue-purple)",
  "var(--bz-hue-green)",
  "var(--bz-hue-magenta)",
  "var(--bz-hue-coral)",
  "var(--bz-hue-amber)",
  "var(--bz-hue-violet)",
  "var(--bz-hue-pink)",
  "var(--bz-hue-red)",
  "var(--bz-hue-yellow)",
] as const;

export function categoryColor(name: string): string {
  const known = NAMED_CATEGORY_COLORS[name];
  if (known !== undefined) {
    return known;
  }
  const trimmed = name.trim();
  if (trimmed === "" || trimmed === "Uncategorized") {
    return "var(--bz-cat-uncat)";
  }
  let hash = 0;
  for (let index = 0; index < trimmed.length; index += 1) {
    hash = (hash * 33 + trimmed.charCodeAt(index)) >>> 0;
  }
  return CATEGORY_HUES[hash % CATEGORY_HUES.length] ?? "var(--bz-cat-uncat)";
}

export function categoryPrimary(name: string): string {
  return name.split(",")[0]?.trim() || name;
}

export function messageFor(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The local workspace is unavailable. Check the API and refresh.";
}
