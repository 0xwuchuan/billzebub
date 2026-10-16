import { describe, expect, it } from "vitest";

import type { Category } from "../api";
import { merchantPickerRows } from "./merchantCategoryPicker";

const categories: Category[] = [
  { id: "groceries", name: "Groceries", parent_id: null, active: true },
  { id: "market", name: "Market", parent_id: "groceries", active: true },
  { id: "transport", name: "Transport", parent_id: null, active: true },
  { id: "uncat", name: "Uncategorized", parent_id: null, active: true },
];

describe("merchant category picker", () => {
  it("lists parents and drills to a Just parent fallback", () => {
    const roots = merchantPickerRows(categories, "", null);
    expect(roots.map((row) => row.name)).toEqual(["Groceries", "Transport"]);
    expect(roots[0]?.hasChildren).toBe(true);
    expect(roots[0]?.categoryId).toBeNull();

    const drilled = merchantPickerRows(categories, "", "groceries");
    expect(drilled.map((row) => row.name)).toEqual([
      "← Groceries",
      "Just Groceries",
      "Groceries › Market",
    ]);
    expect(drilled[1]?.kind).toBe("just");
    expect(drilled[1]?.categoryId).toBe("groceries");
    expect(drilled[2]?.categoryId).toBe("market");
  });

  it("assigns a parent that has no children in one step", () => {
    const roots = merchantPickerRows(categories, "", null);
    expect(roots.find((row) => row.name === "Transport")?.categoryId).toBe(
      "transport",
    );
  });
});
