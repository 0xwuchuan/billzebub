import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const shell = readFileSync("src/styles/shell.css", "utf8");
const base = readFileSync("src/styles/base.css", "utf8");
const screens = readFileSync("src/styles/screens.css", "utf8");

function blockAfter(source: string, marker: string): string {
  const start = source.indexOf(marker);
  expect(start).toBeGreaterThanOrEqual(0);
  return source.slice(start);
}

describe("phone layout contracts", () => {
  it("keeps the entrance animation from trapping fixed chrome", () => {
    const keyframes = base.slice(
      base.indexOf("@keyframes stage-enter"),
      base.indexOf("@keyframes bar-rise"),
    );
    expect(keyframes).not.toMatch(/transform/);
  });

  it("gives phone icon buttons, including the theme toggle, a 44px target", () => {
    const phone = blockAfter(shell, "@media (max-width: 52rem)");
    expect(phone).toMatch(/\.icon-btn\s*\{[^}]*min-width:\s*2\.75rem/);
    expect(phone).toMatch(/\.icon-btn\s*\{[^}]*min-height:\s*2\.75rem/);
  });

  it("anchors the transaction sheet to the bottom of the phone viewport", () => {
    const phone = blockAfter(shell, "@media (max-width: 52rem)");
    const drawer = phone.slice(
      phone.indexOf(".drawer {"),
      phone.indexOf(".drawer.open"),
    );
    expect(drawer).toMatch(/bottom:\s*0/);
    expect(drawer).toMatch(/top:\s*auto/);
  });

  it("lets the settings dialog body scroll inside the dialog", () => {
    expect(screens).toMatch(/\.settings-dialog\s*\{[^}]*display:\s*flex/);
    expect(screens).toMatch(
      /\.settings-dialog-body\s*\{[^}]*overflow-y:\s*auto/,
    );
    expect(screens).toMatch(/\.settings-dialog-body\s*\{[^}]*min-height:\s*0/);
  });

  it("clears the transactions bulk bar, including the safe area", () => {
    const phone = blockAfter(screens, "@media (max-width: 52rem)");
    expect(phone).toMatch(
      /\.tx-page\.has-bulk\s*\{[^}]*safe-area-inset-bottom/,
    );
    const bulk = phone.slice(phone.indexOf(".bulk-bar {"));
    expect(bulk).toMatch(/transform:\s*none/);
    expect(bulk).not.toMatch(/translateX/);
  });
});
