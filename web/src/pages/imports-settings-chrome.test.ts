import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const imports = readFileSync("src/pages/ImportsPage.tsx", "utf8");
const settings = readFileSync("src/pages/SettingsPage.tsx", "utf8");
const coverage = readFileSync(
  "src/components/StatementCoveragePanel.tsx",
  "utf8",
);
const accounts = readFileSync(
  "src/components/settings/AccountsPanel.tsx",
  "utf8",
);
const categories = readFileSync(
  "src/components/settings/CategoriesPanel.tsx",
  "utf8",
);
const screens = readFileSync("src/styles/screens.css", "utf8");
const base = readFileSync("src/styles/base.css", "utf8");

describe("imports and settings chrome", () => {
  it("strips inline styles from imports and coverage", () => {
    expect(imports).not.toMatch(/style=\{\{/);
    expect(coverage).not.toMatch(/style=\{\{/);
    expect(settings).not.toMatch(/style=\{\{/);
  });

  it("paints coverage chips from status tokens", () => {
    const block = screens.slice(
      screens.indexOf(".coverage-chip.is-present"),
      screens.indexOf(".import-summary {"),
    );
    expect(block).toMatch(/--bz-confirmed/);
    expect(block).toMatch(/--bz-provisional/);
    expect(block).toMatch(/--bz-blocking/);
    expect(block).toMatch(/16%/);
    expect(block).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    expect(block).not.toMatch(/border-color:\s*color-mix/);
  });

  it("selects a coverage row with a quiet fill", () => {
    const selected = screens.slice(
      screens.indexOf(".coverage-row.is-selected"),
      screens.indexOf(".coverage-account {"),
    );
    expect(selected).toMatch(/12%/);
    expect(selected).toMatch(/--bz-bg-card/);
    expect(selected).not.toMatch(/inset/);
    expect(selected).not.toMatch(/--bz-accent/);
  });

  it("keeps taxonomy on CategoryChip and import status on Badge", () => {
    expect(categories).toMatch(/CategoryChip name=\{category\.name\}/);
    expect(categories).toMatch(/CategoryChip name="Uncategorized"/);
    expect(accounts).toMatch(/Badge/);
    expect(accounts).not.toMatch(/CategoryChip/);
    expect(accounts).not.toMatch(/ProvisionalBadge/);
    expect(imports).toMatch(/Badge/);
    expect(imports).not.toMatch(/CategoryChip/);
    expect(imports).not.toMatch(/ProvisionalBadge/);
    expect(coverage).not.toMatch(/CategoryChip/);
    expect(coverage).not.toMatch(/ProvisionalBadge/);
    expect(settings).not.toMatch(/ProvisionalBadge/);
    expect(settings).not.toMatch(/CategoryChip/);
  });

  it("uses teal dialog actions and hides the phone appearance toggle", () => {
    const dialog = screens.slice(
      screens.indexOf(".settings-dialog {"),
      screens.indexOf(".imports-stage {"),
    );
    expect(dialog).toMatch(/--bz-bg-card/);
    expect(dialog).toMatch(/--bz-action/);
    expect(dialog).toMatch(/--bz-on-accent/);
    expect(dialog).toMatch(/--bz-shadow/);
    expect(dialog).not.toMatch(/#[0-9a-fA-F]{3,8}/);

    const phone = screens.slice(screens.indexOf("@media (max-width: 52rem)"));
    expect(phone).toMatch(
      /\.settings-appearance \.theme-toggle\s*\{[^}]*display:\s*none/,
    );
  });

  it("focuses import and coverage controls with the existing outline", () => {
    expect(base).toMatch(/\.queue-item:focus-visible/);
    expect(base).toMatch(/\.coverage-account:focus-visible/);
    expect(base).toMatch(/outline:\s*2px solid var\(--bz-accent\)/);
  });
});
