import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const page = readFileSync("src/pages/TransactionsPage.tsx", "utf8");
const drawer = readFileSync("src/components/TransactionDrawer.tsx", "utf8");
const chip = readFileSync("src/components/ui/CategoryChip.tsx", "utf8");
const screens = readFileSync("src/styles/screens.css", "utf8");
const shell = readFileSync("src/styles/shell.css", "utf8");
const base = readFileSync("src/styles/base.css", "utf8");

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

  it("splits the desk list and detail in flow and keeps the phone overlay", () => {
    const desk = screens.slice(screens.indexOf("@media (min-width: 52.01rem)"));
    expect(desk).toMatch(
      /grid-template-columns:\s*minmax\(0,\s*45fr\)\s*minmax\(0,\s*55fr\)/,
    );
    expect(desk).toMatch(/\.tx-page\.has-detail \.tx-detail/);
    expect(desk).toMatch(/\.tx-page\.has-detail \.bulk-bar/);
    expect(desk).not.toMatch(/\.drawer-backdrop/);
    expect(desk).not.toMatch(/position:\s*fixed/);
    expect(screens).not.toMatch(/\.app\.has-detail \.bulk-bar/);
    expect(shell).not.toMatch(/var\(--bz-detail\)/);

    const phone = shell.slice(shell.indexOf("@media (max-width: 52rem)"));
    expect(phone).toMatch(/\.drawer\s*\{[^}]*bottom:\s*0/);
    expect(shell).toMatch(/\.drawer-backdrop/);
    expect(drawer).toMatch(/confirm-status is-confirmed/);
    expect(drawer).toMatch(/confirm-dot/);
    expect(drawer).toMatch(/role="dialog"/);
    expect(drawer).toMatch(/className="tx-detail"/);
  });

  it("gives a desktop transaction chip a real width and no hue dot", () => {
    expect(chip).not.toMatch(/cat-chip-dot/);
    expect(base).not.toMatch(/\.cat-chip\s*\{[^}]*container-type/);
    const status = screens.slice(
      screens.indexOf(".tx-row-status {"),
      screens.indexOf(".tx-amount-side {"),
    );
    expect(status).toMatch(/flex:\s*0 0 auto/);
    expect(status).toMatch(/max-width:\s*16rem/);
    expect(screens).toMatch(/\.tx-row \.cat-chip\s*\{[^}]*max-width:\s*16rem/);
  });
});
