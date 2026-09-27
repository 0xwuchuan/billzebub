import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const page = readFileSync("src/pages/TransactionsPage.tsx", "utf8");
const drawer = readFileSync("src/components/TransactionDrawer.tsx", "utf8");
const screens = readFileSync("src/styles/screens.css", "utf8");
const shell = readFileSync("src/styles/shell.css", "utf8");

describe("transactions chrome", () => {
  it("uses TxRow dots so CategoryChip stays the only pill", () => {
    expect(page).toMatch(/provisionalMark="dot"/);
    expect(page).not.toMatch(/ProvisionalBadge/);
    expect(drawer).toMatch(/CategoryChip/);
    expect(drawer).not.toMatch(/ProvisionalBadge/);
    expect(drawer).not.toMatch(/badge-provisional/);
    expect(drawer).toMatch(/confirm-status is-provisional/);
  });

  it("paints the toolbar, bulk bar, and provisional status from tokens", () => {
    const chips = screens.slice(
      screens.indexOf(".tx-toolbar .chip {"),
      screens.indexOf(".add-filter {"),
    );
    expect(chips).toMatch(/--bz-bg-elevated/);
    expect(chips).not.toMatch(/--bz-accent/);
    expect(chips).not.toMatch(/#[0-9a-fA-F]{3,8}/);

    const bulk = screens.slice(
      screens.indexOf(".bulk-bar {"),
      screens.indexOf(".theme-row {"),
    );
    expect(bulk).toMatch(/--bz-bg-card/);
    expect(bulk).toMatch(/--bz-action/);
    expect(bulk).toMatch(/--bz-shadow/);
    expect(bulk).not.toMatch(/#[0-9a-fA-F]{3,8}/);

    const selected = screens.slice(
      screens.indexOf(".tx-row.is-selected"),
      screens.indexOf(".tx-check {"),
    );
    expect(selected).toMatch(/box-shadow:\s*none/);
    expect(selected).not.toMatch(/inset/);

    expect(shell).toMatch(/--bz-status-provisional/);
    expect(shell).not.toMatch(/#[0-9a-fA-F]{3,8}/);
  });
});
