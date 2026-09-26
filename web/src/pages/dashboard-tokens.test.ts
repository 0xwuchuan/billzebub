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
    expect(overview).not.toMatch(/ProvisionalBadge/);
    expect(spending).toMatch(/CategoryRankList/);
    expect(spending).toMatch(/onOpenTransactions/);
  });
});
