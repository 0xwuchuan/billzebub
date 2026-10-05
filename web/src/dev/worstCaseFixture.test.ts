import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { isFixtureMode, readFixtureMode } from "./fixtureMode";
import { recurringsFor, workspaceFor } from "./worstCaseFixture";

describe("example-data fixture", () => {
  it("accepts only the dev toggle values", () => {
    expect(isFixtureMode("worst")).toBe(true);
    expect(isFixtureMode("empty")).toBe(true);
    expect(isFixtureMode("one")).toBe(true);
    expect(isFixtureMode("1000")).toBe(true);
    expect(isFixtureMode("demo")).toBe(false);
    expect(readFixtureMode("")).toBeNull();
    expect(readFixtureMode("?data=worst")).toBe("worst");
    expect(readFixtureMode("?data=nope")).toBeNull();
  });

  it("builds an empty ledger, a single row, and a 1000-row list", () => {
    const empty = workspaceFor("empty");
    expect(empty.transactions.items).toHaveLength(0);
    expect(empty.reviews).toHaveLength(0);
    expect(empty.imports).toHaveLength(0);
    expect(empty.accounts).toHaveLength(0);
    expect(recurringsFor("empty").proposed).toHaveLength(0);

    const one = workspaceFor("one");
    expect(one.transactions.items).toHaveLength(1);
    expect(one.reviews).toHaveLength(1);
    expect(one.imports).toHaveLength(1);
    expect(one.imports[0]?.claim_count).toBe(1);
    expect(recurringsFor("one").proposed).toHaveLength(1);
    expect(recurringsFor("one").active).toHaveLength(1);

    expect(workspaceFor("1000").transactions.items).toHaveLength(1000);
    expect(workspaceFor("1000").transactions.next_cursor).toBeNull();
  });

  it("spreads plausible worst-case values across the first rows", () => {
    const workspace = workspaceFor("worst", { includeDismissed: true });
    const names = workspace.transactions.items.map((item) => item.counterparty);
    expect(names.some((name) => name.length === 300)).toBe(true);
    expect(names).toContain(
      "https://example.com/workspaces/acme/projects/q3-launch/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved",
    );
    expect(names).toContain("王秀英");
    expect(names).toContain("🦊 Fox Street Market");
    expect(names).toContain("👩🏽‍💻 Priya Design Studio");
    expect(names).toContain("");
    expect(
      workspace.transactions.items.some(
        (item) => item.posted_amount.amount === "1234567.89",
      ),
    ).toBe(true);
    expect(
      workspace.transactions.items.some((item) => item.kind === "refund"),
    ).toBe(true);
    expect(
      workspace.transactions.items.some(
        (item) => item.category_splits.length === 0,
      ),
    ).toBe(true);
    expect(
      workspace.accounts.some((account) => account.display_name.length === 160),
    ).toBe(true);
    expect(
      workspace.imports.some((item) => item.failure_code?.length === 120),
    ).toBe(true);
    expect(workspace.reviews.length).toBeGreaterThan(1);
    expect(workspace.identity?.login).toBe("example.owner@example.com");
    expect(
      workspaceFor("worst").imports.every((item) => item.dismissed_at === null),
    ).toBe(true);
  });

  it("is referenced only from a dev-gated dynamic import", () => {
    const workspace = readFileSync("src/hooks/useWorkspace.ts", "utf8");
    const recurrings = readFileSync("src/hooks/useRecurrings.ts", "utf8");
    expect(workspace).not.toMatch(/^import .*worstCaseFixture/m);
    expect(recurrings).not.toMatch(/^import .*worstCaseFixture/m);
    expect(workspace).toMatch(/import\.meta\.env\.DEV && mode !== null/);
    expect(recurrings).toMatch(
      /import\.meta\.env\.DEV && fixtureMode !== null/,
    );
    expect(workspace).toContain('import("../dev/worstCaseFixture")');
    expect(recurrings).toContain('import("../dev/worstCaseFixture")');
  });
});
