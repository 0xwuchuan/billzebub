export type WatchAccount = {
  id: string;
  name: string;
  kind: string;
  inbox: string;
  artifacts: Array<{ file: string; parser: string; ok: boolean }>;
};

export const WATCH_ACCOUNTS: WatchAccount[] = [
  {
    id: "dbs",
    name: "DBS Live Fresh",
    kind: "Credit card",
    inbox: "/volume1/Billzebub-Inbox/dbs-live-fresh",
    artifacts: [
      {
        file: "dbs-live-fresh-2026-09.pdf",
        parser: "dbs_credit_card v3",
        ok: true,
      },
      {
        file: "dbs-live-fresh-2026-08.pdf",
        parser: "parser matched, totals unverified",
        ok: false,
      },
    ],
  },
  {
    id: "citi",
    name: "Citi Cash Back+",
    kind: "Credit card",
    inbox: "/volume1/Billzebub-Inbox/citi-cash-back",
    artifacts: [
      {
        file: "citi-cash-back-2026-09.pdf",
        parser: "citi_credit_card v2",
        ok: true,
      },
    ],
  },
  {
    id: "uob",
    name: "UOB Lady's Card",
    kind: "Credit card",
    inbox: "/volume1/Billzebub-Inbox/uob-ladys",
    artifacts: [
      { file: "uob-ladys-2026-09.pdf", parser: "uob_credit_card v2", ok: true },
    ],
  },
  {
    id: "paylah",
    name: "DBS PayLah",
    kind: "Wallet",
    inbox: "/volume1/Billzebub-Inbox/paylah",
    artifacts: [
      { file: "paylah-2026-09.eml", parser: "paylah_wallet v1", ok: true },
    ],
  },
];

export const SETUP_CATEGORIES = [
  "Groceries",
  "Dining",
  "Transport",
  "Utilities",
  "Health",
  "Shopping",
] as const;

export function accountById(id: string): WatchAccount | undefined {
  return WATCH_ACCOUNTS.find((account) => account.id === id);
}
