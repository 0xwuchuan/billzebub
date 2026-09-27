import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const overview = readFileSync("src/pages/OverviewPage.tsx", "utf8");
const spending = readFileSync("src/pages/SpendingPage.tsx", "utf8");
const charts = readFileSync(
  "src/components/dither-kit/DitherCharts.tsx",
  "utf8",
);
const series = readFileSync("src/lib/chartSeries.ts", "utf8");

describe("dashboard chart series", () => {
  it("keeps Overview and Spending series on tokens", () => {
    for (const source of [overview, spending, charts, series]) {
      expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    }
    expect(series).toMatch(/var\(--bz-status-confirmed\)/);
    expect(series).toMatch(/var\(--bz-status-provisional\)/);
    expect(series).toMatch(/variant: "soft"/);
  });

  it("uses CategoryChip for category lists and TxRow for recent activity", () => {
    expect(overview).toMatch(/CategoryRankList/);
    expect(overview).toMatch(/provisionalMark="dot"/);
    expect(overview).toMatch(/density="compact"/);
    expect(overview).toMatch(/slice\(0, RECENT_LIMIT\)/);
    expect(overview).toMatch(/limit=\{5\}/);
    expect(overview).toMatch(/figures="amount"/);
    expect(overview).not.toMatch(/ProvisionalBadge/);
    expect(spending).toMatch(/CategoryRankList/);
    expect(spending).toMatch(/onOpenTransactions/);
    expect(spending).toMatch(/Spent this month/);
    expect(spending).toMatch(/Six-month estimate/);
    expect(spending).toMatch(/Spending by month/);
    expect(spending).not.toMatch(/Net worth|Recurring|Investments/);
  });
});

describe("overview bento chrome", () => {
  const screens = readFileSync("src/styles/screens.css", "utf8");

  it("gives the month hero two thirds and stacks the four jobs on a phone", () => {
    expect(screens).toMatch(
      /\.bento-top\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*2fr\)\s*minmax\(11\.5rem,\s*1fr\)/,
    );
    expect(screens).toMatch(
      /\.bento-bottom\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*minmax\(0,\s*1fr\)/,
    );
    const phone = screens.slice(screens.indexOf("@media (max-width: 52rem)"));
    expect(phone).toMatch(
      /\.bento-top,\s*\n\s*\.bento-bottom,\s*\n\s*\.bento-hero-main\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
  });

  it("tints Attention only when the queue is open and keeps chart fills on tokens", () => {
    expect(overview).toMatch(/has-queue/);
    expect(screens).toMatch(
      /\.bento-attention\.has-queue\s*\{[^}]*--bz-attention/,
    );
    expect(screens).toMatch(/\.bento-figure\s*\{[^}]*--bz-text-display/);
    const bento = screens.slice(
      screens.indexOf(".bento-hero-body,"),
      screens.indexOf(".dash-card {"),
    );
    expect(bento).not.toMatch(/#[0-9a-fA-F]{3,8}/);
  });
});
