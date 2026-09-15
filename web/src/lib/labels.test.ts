import { describe, expect, it } from "vitest";

import { formatOwnerCardLabel } from "./labels";

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
});
