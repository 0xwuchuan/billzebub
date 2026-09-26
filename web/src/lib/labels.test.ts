import { describe, expect, it } from "vitest";

import {
  categoryColor,
  dateGroupLabel,
  formatOwnerCardLabel,
  shortMonthLabel,
} from "./labels";

describe("formatOwnerCardLabel", () => {
  it("shows card names without bullet-masking", () => {
    expect(formatOwnerCardLabel("Citi PremierMiles")).toBe("Citi PremierMiles");
    expect(formatOwnerCardLabel("  DBS Woman's World  ")).toBe(
      "DBS Woman's World",
    );
    expect(formatOwnerCardLabel("Citi PremierMiles")).not.toMatch(/•{2,}/);
  });

  it("shows last4 digits instead of masking them", () => {
    expect(formatOwnerCardLabel("4321")).toBe("4321");
    expect(formatOwnerCardLabel("Visa 8899")).toBe("Visa • 8899");
    expect(formatOwnerCardLabel("DBS Live Fresh •••• 1234")).toBe(
      "DBS Live Fresh • 1234",
    );
    expect(formatOwnerCardLabel("4321")).not.toMatch(/•/);
  });

  it("abbreviates calendar months for coverage chips", () => {
    expect(shortMonthLabel("2026-04")).toBe("Apr");
    expect(shortMonthLabel("2026-09")).toBe("Sep");
  });
});

describe("categoryColor", () => {
  it("maps named categories and leaves Uncategorized muted", () => {
    expect(categoryColor("Groceries")).toBe("var(--bz-cat-groceries)");
    expect(categoryColor("Dining")).toBe("var(--bz-cat-dining)");
    expect(categoryColor("Uncategorized")).toBe("var(--bz-cat-uncat)");
    expect(categoryColor("")).toBe("var(--bz-cat-uncat)");
  });

  it("assigns other categories a stable hue token", () => {
    const color = categoryColor("School");
    expect(color).toMatch(/^var\(--bz-hue-/);
    expect(categoryColor("School")).toBe(color);
    expect(color).not.toMatch(/#[0-9a-fA-F]{3,8}/);
  });
});

describe("dateGroupLabel", () => {
  it("uses Today, Yesterday, and a weekday heading", () => {
    const today = new Date(2026, 0, 12);
    expect(dateGroupLabel("2026-01-12", today)).toBe("Today");
    expect(dateGroupLabel("2026-01-11", today)).toBe("Yesterday");
    expect(dateGroupLabel("2026-01-10", today)).toBe("Saturday, January 10");
  });
});
