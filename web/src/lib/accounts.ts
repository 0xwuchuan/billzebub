import type { FinancialAccount } from "../api";

export const SETUP_CATEGORIES = [
  "Groceries",
  "Dining",
  "Transport",
  "Utilities",
  "Health",
  "Shopping",
  "Gifts",
] as const;

export const SETUP_ACCOUNT_EXAMPLES = [
  {
    slug: "citi-premiermiles",
    displayName: "Citi PremierMiles",
    institution: "citi",
  },
  {
    slug: "citi-rewards",
    displayName: "Citi Rewards",
    institution: "citi",
  },
  {
    slug: "dbs-womans-world",
    displayName: "DBS Woman's World",
    institution: "dbs",
  },
  {
    slug: "uob-ppv",
    displayName: "UOB PPV",
    institution: "uob",
  },
] as const;

const KIND_ORDER = ["credit_card", "paylah", "depository"] as const;

export type AccountGroup = {
  kind: string;
  label: string;
  accounts: FinancialAccount[];
};

export function accountKindLabel(kind: string): string {
  if (kind === "credit_card") {
    return "Credit card";
  }
  if (kind === "paylah") {
    return "PayLah";
  }
  if (kind === "depository") {
    return "Depository";
  }
  return kind
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function accountKindColor(kind: string): string {
  if (kind === "credit_card") {
    return "var(--bz-accent)";
  }
  if (kind === "paylah") {
    return "var(--bz-positive)";
  }
  if (kind === "depository") {
    return "var(--bz-cat-utilities)";
  }
  return "var(--bz-muted)";
}

export function groupedAccounts(accounts: FinancialAccount[]): AccountGroup[] {
  const map = new Map<string, FinancialAccount[]>();
  for (const account of accounts) {
    if (!account.active) {
      continue;
    }
    const current = map.get(account.kind) ?? [];
    current.push(account);
    map.set(account.kind, current);
  }
  return [...map.entries()]
    .sort(([left], [right]) => kindRank(left) - kindRank(right))
    .map(([kind, grouped]) => ({
      kind,
      label: accountKindLabel(kind),
      accounts: grouped,
    }));
}

function kindRank(kind: string): number {
  const index = KIND_ORDER.indexOf(kind as (typeof KIND_ORDER)[number]);
  return index === -1 ? KIND_ORDER.length : index;
}
