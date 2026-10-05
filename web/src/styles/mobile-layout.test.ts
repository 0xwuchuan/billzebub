import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const shell = readFileSync("src/styles/shell.css", "utf8");
const base = readFileSync("src/styles/base.css", "utf8");
const screens = readFileSync("src/styles/screens.css", "utf8");
const html = readFileSync("index.html", "utf8");

function withoutHoverMedia(source: string): string {
  const needle = "@media (hover: hover) and (pointer: fine)";
  let result = "";
  let index = 0;
  while (index < source.length) {
    const at = source.indexOf(needle, index);
    if (at === -1) {
      result += source.slice(index);
      break;
    }
    result += source.slice(index, at);
    const open = source.indexOf("{", at);
    let depth = 0;
    let cursor = open;
    for (; cursor < source.length; cursor += 1) {
      const char = source[cursor];
      if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          cursor += 1;
          break;
        }
      }
    }
    index = cursor;
  }
  return result;
}

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

  it("keeps phone drawer section labels in flow above their groups", () => {
    const groups = shell.slice(
      shell.indexOf(".nav-drawer .rail-group,"),
      shell.indexOf(".nav-drawer .rail-item"),
    );
    expect(groups).toMatch(/\.nav-drawer \.rail-accounts/);
    expect(groups).toMatch(/flex-shrink:\s*0/);
    expect(groups).toMatch(/min-height:\s*auto/);
    expect(groups).not.toMatch(/min-height:\s*0/);
    expect(groups).not.toMatch(/position:\s*absolute/);
    expect(groups).not.toMatch(/position:\s*sticky/);
    expect(groups).not.toMatch(/margin-top:\s*-/);
  });

  it("keeps the phone theme toggle in the top bar", () => {
    const phone = blockAfter(shell, "@media (max-width: 52rem)");
    expect(phone).toMatch(
      /\.nav-drawer \.rail-foot \.theme-toggle\s*\{[^}]*display:\s*none/,
    );
  });

  it("gives transaction checkboxes a 44px phone hit target", () => {
    const phone = blockAfter(screens, "@media (max-width: 52rem)");
    const check = phone.slice(
      phone.indexOf(".tx-check {"),
      phone.indexOf(".tx-check input"),
    );
    expect(check).toMatch(/min-width:\s*2\.75rem/);
    expect(check).toMatch(/min-height:\s*2\.75rem/);
  });

  it("lets phone counterparty names use two lines instead of one clipped line", () => {
    const phone = blockAfter(screens, "@media (max-width: 52rem)");
    const name = phone.slice(phone.indexOf(".tx-row-copy strong {"));
    expect(name).toMatch(/white-space:\s*normal/);
    expect(name).toMatch(/-webkit-line-clamp:\s*2/);
  });

  it("lets transaction filter chips share a row", () => {
    const phone = blockAfter(screens, "@media (max-width: 52rem)");
    const filter = phone.slice(
      phone.indexOf(".add-filter {"),
      phone.indexOf(".add-filter-menu"),
    );
    expect(filter).toMatch(/width:\s*auto/);
    expect(filter).not.toMatch(/width:\s*100%/);
  });

  it("pins phone Review actions in a dock and scrolls only the category list", () => {
    const phoneStart = screens.indexOf("@media (max-width: 52rem)");
    const phoneEnd = screens.indexOf("@media (min-width: 52.01rem)");
    const phone = screens.slice(phoneStart, phoneEnd);
    const desk = screens.slice(0, phoneStart);
    expect(phone).toMatch(
      /\.stage:has\(\.review-page\)\s*\{[^}]*overflow:\s*hidden/,
    );
    expect(phone).toMatch(
      /\.review-page \.decision-subject\s*\{[^}]*-webkit-line-clamp:\s*2/,
    );
    expect(phone).toMatch(
      /\.review-page \.cat-picker-list\s*\{[^}]*overflow:\s*auto/,
    );
    expect(phone).toMatch(
      /\.review-page \.cat-picker-list\s*\{[^}]*max-height:\s*none/,
    );
    const dock = phone.slice(
      phone.indexOf(".review-page .review-action-dock {"),
    );
    expect(dock).toMatch(/safe-area-inset-bottom/);
    expect(dock).toMatch(/border-top:\s*1px solid var\(--bz-border\)/);
    expect(dock).toMatch(/background:\s*var\(--bz-bg-card\)/);
    expect(desk).not.toMatch(/\.review-action-dock/);
  });

  it("does not stretch an empty Review card to the viewport", () => {
    const tablet = blockAfter(screens, "@media (max-width: 64rem)");
    const empty = tablet.slice(tablet.indexOf(".evidence-pane.is-empty"));
    expect(empty).toMatch(/min-height:\s*0/);
  });

  it("keeps hover rules behind a fine pointer", () => {
    for (const source of [base, shell, screens]) {
      expect(withoutHoverMedia(source)).not.toMatch(/:hover/);
      expect(source).toMatch(/@media \(hover: hover\) and \(pointer: fine\)/);
    }
  });

  it("uses dynamic viewport units and keeps zoom enabled", () => {
    const css = `${base}\n${shell}\n${screens}`;
    expect(css).not.toMatch(/100vh/);
    expect(css).toMatch(/minmax\(40vh,\s*1fr\)/);
    expect(html).toMatch(/viewport-fit=cover/);
    expect(html).toMatch(/interactive-widget=resizes-content/);
    expect(html).not.toMatch(/maximum-scale|user-scalable/);
    expect(html).toMatch(/theme-color/);
    expect(html).toMatch(/#e6e4d9/);
    expect(html).toMatch(/#100f0f/);
    expect(html).not.toMatch(/#f2f0e5|#1c1b1a/);
  });

  it("sets the mobile baseline on the document and controls", () => {
    expect(base).toMatch(/-webkit-tap-highlight-color:\s*transparent/);
    expect(base).toMatch(/overscroll-behavior:\s*none/);
    expect(base).toMatch(
      /@media \(pointer: coarse\)\s*\{\s*input,\s*textarea,\s*select\s*\{\s*\/\*[^*]*\*\/\s*font-size:\s*16px;/,
    );
    expect(base.slice(0, base.indexOf("@media (pointer: coarse)"))).not.toMatch(
      /font-size:\s*16px/,
    );
    expect(base).toMatch(/touch-action:\s*manipulation/);
    expect(base).not.toMatch(/body\s*\{[^}]*user-select:\s*none/);
    expect(base).toMatch(/\.amount,\s*\n\.tx-amount[\s\S]*user-select:\s*text/);
  });

  it("presses wide surfaces with a background instead of a scale", () => {
    const scale = base.slice(
      base.indexOf(".btn:active"),
      base.indexOf(".recurring-strip,"),
    );
    expect(scale).toMatch(/transform:\s*scale\(var\(--bz-press\)\)/);
    for (const selector of [
      ".queue-item:active",
      ".tx-row-main:active",
      ".cat-row:active",
      ".recurring-strip:active",
      ".bento-attention-hit:active",
    ]) {
      expect(scale).not.toContain(selector);
    }
    expect(base).toMatch(
      /\.recurring-strip:active,\s*\n\.bento-attention-hit:active\s*\{[^}]*background:\s*var\(--bz-surface-hover\)/,
    );
    expect(base).toMatch(
      /\.tx-row-main:active,[\s\S]*?background:\s*color-mix\(in srgb, var\(--bz-text\) 6%, var\(--bz-bg-card\)\)/,
    );
    const reduced = base.slice(
      base.indexOf("@media (prefers-reduced-motion: reduce)"),
    );
    expect(reduced).toMatch(/transform:\s*none/);
    expect(reduced).not.toMatch(
      /\.queue-item:active|\.tx-row-main:active|\.cat-row:active|\.recurring-strip:active|\.bento-attention-hit:active/,
    );
  });

  it("pads the phone drawer and sheets away from the notch", () => {
    const drawer = shell.slice(
      shell.indexOf(".nav-drawer.open"),
      shell.indexOf(".nav-drawer .rail-body"),
    );
    expect(drawer).toMatch(/safe-area-inset-top/);
    expect(drawer).toMatch(/safe-area-inset-bottom/);
    expect(drawer).toMatch(/safe-area-inset-left/);
    expect(shell).toMatch(
      /\.drawer-body\s*\{[^}]*overscroll-behavior:\s*contain/,
    );
    expect(screens).toMatch(
      /\.settings-dialog-body\s*\{[^}]*overscroll-behavior:\s*contain/,
    );
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
