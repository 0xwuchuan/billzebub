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

  it("paints missing months in provisional text and present months in muted text", () => {
    const months = screens.slice(
      screens.indexOf(".coverage-chip.is-present"),
      screens.indexOf(".imports-stage .panel-head h2"),
    );
    expect(months).toMatch(
      /\.coverage-chip\.is-missing\s*\{[^}]*color:\s*var\(--bz-provisional\)/,
    );
    expect(months).toMatch(
      /\.coverage-chip\.is-present\s*\{[^}]*color:\s*var\(--bz-muted\)/,
    );
    expect(months).not.toMatch(/--bz-confirmed/);
    expect(months).not.toMatch(/--bz-blocking/);
    expect(months).not.toMatch(
      /background:\s*color-mix\(\s*in srgb,\s*var\(--coverage-tone\)/,
    );
    expect(months).not.toMatch(/#[0-9a-fA-F]{3,8}/);

    const counts = screens.slice(
      screens.indexOf(".coverage-count.is-missing"),
      screens.indexOf(".coverage-head h2"),
    );
    expect(counts).toMatch(/--bz-provisional/);
    expect(counts).toMatch(/--bz-muted/);
    expect(counts).not.toMatch(/--bz-confirmed/);
    expect(counts).not.toMatch(/--bz-blocking/);
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
    expect(base).toMatch(/\.coverage-toggle:focus-visible/);
    expect(base).toMatch(/outline:\s*2px solid var\(--bz-accent\)/);
  });

  it("keeps coverage collapsed by default and gives Extractions the stage", () => {
    expect(coverage).toMatch(/bz\.imports\.coverageExpanded/);
    expect(coverage).not.toMatch(/coverage-status/);
    expect(coverage).toMatch(/aria-expanded/);
    expect(imports).toMatch(/Failed/);
    expect(imports).toMatch(/Accepted/);
    expect(imports).not.toMatch(/CategoryChip/);

    const desk = screens.slice(
      screens.indexOf(".imports-stage:has(.coverage-panel.is-collapsed)"),
    );
    expect(desk).toMatch(/minmax\(0,\s*1fr\)/);
    expect(desk).toMatch(/minmax\(40vh,\s*1fr\)/);
    expect(desk).toMatch(/overflow:\s*auto/);
  });
});
