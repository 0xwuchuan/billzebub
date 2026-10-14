import { describe, expect, it } from "vitest";

import type { Category, Transaction } from "../api";
import {
  buildPickerRows,
  categorySpend,
  reducePickerKey,
  closedPicker,
  spendReconciles,
} from "./categoryTree";

const food: Category = {
  id: "food",
  name: "Food",
  parent_id: null,
  active: true,
};
const dining: Category = {
  id: "dining",
  name: "Dining",
  parent_id: "food",
  active: true,
};
const groceries: Category = {
  id: "groceries",
  name: "Groceries",
  parent_id: "food",
  active: true,
};
const transport: Category = {
  id: "transport",
  name: "Transport",
  parent_id: null,
  active: true,
};
const health: Category = {
  id: "health",
  name: "Health",
  parent_id: null,
  active: true,
};
const sameName: Category = {
  id: "food-dining",
  name: "Food",
  parent_id: "transport",
  active: true,
};

function expense(
  id: string,
  category: Category,
  cents: number,
  provisional = false,
): Transaction {
  const amount = (cents / 100).toFixed(2);
  return {
    id,
    version: 1,
    financial_account: { id: "acct", name: "Card" },
    counterparty: id,
    posted_amount: {
      amount: provisional ? "0.00" : `-${amount}`,
      currency: "SGD",
    },
    authorized_amount: provisional
      ? { amount: `-${amount}`, currency: "SGD" }
      : null,
    effective_date: "2026-03-04",
    kind: "expense",
    category_splits: [
      {
        id: category.id,
        name: category.name,
        amount: { amount, currency: "SGD" },
      },
    ],
    reviews: [],
  };
}

describe("category spend rollup", () => {
  it("reconciles a parent with direct spend, children, and unsorted last", () => {
    const groups = categorySpend(
      [
        expense("direct", food, 1000),
        expense("dining", dining, 1500),
        expense("groceries", groceries, 500),
        expense("provisional", dining, 200, true),
        expense("transport", transport, 700),
      ],
      "2026-03",
      [food, dining, groceries, transport],
    );

    const parent = groups.find((group) => group.id === food.id);
    expect(parent).toBeDefined();
    expect(parent?.cents).toBe(3200);
    expect(parent?.directCents).toBe(1000);
    expect(parent?.provisional).toBe(true);
    expect(parent?.children.map((child) => child.name)).toEqual([
      "Dining",
      "Groceries",
      "Food (unsorted)",
    ]);
    expect(groups.every(spendReconciles)).toBe(true);
    expect(groups.reduce((sum, group) => sum + group.cents, 0)).toBe(3900);
  });

  it("hides a parent whose children and direct spend are all zero", () => {
    const groups = categorySpend([], "2026-03", [food, dining]);
    expect(groups).toEqual([]);
  });

  it("shows only the unsorted row when every child is zero", () => {
    const groups = categorySpend([expense("direct", food, 800)], "2026-03", [
      food,
      dining,
      groceries,
    ]);
    expect(groups[0]?.children.map((child) => child.name)).toEqual([
      "Food (unsorted)",
    ]);
    expect(groups[0]?.cents).toBe(800);
    expect(spendReconciles(groups[0]!)).toBe(true);
  });
});

describe("category picker", () => {
  const catalog = [food, dining, groceries, transport, health, sameName];

  it("assigns a flat category in one step and drills a parent", () => {
    const state = { ...closedPicker, open: true };
    const rows = buildPickerRows({
      categories: catalog,
      query: "",
      parentId: null,
      placing: false,
      selectedId: null,
      recentIds: [],
      usage: new Map([
        ["dining", 4],
        ["food", 1],
      ]),
    });
    expect(rows.find((row) => row.name === "Health")?.hasChildren).toBe(false);
    const parent = rows.find((row) => row.name === "Food");
    expect(parent?.hasChildren).toBe(true);
    expect(parent?.hint).toBe("2");
    const drilled = reducePickerKey(state, rows, "Enter");
    expect(drilled.state.parentId).toBe("food");
    const children = buildPickerRows({
      categories: catalog,
      query: "",
      parentId: "food",
      placing: false,
      selectedId: dining.id,
      recentIds: [],
      usage: new Map(),
    });
    expect(children[1]?.name).toBe("Just Food");
    expect(children.map((row) => row.label)).toContain("Dining");
    const assigned = reducePickerKey(
      { ...state, parentId: "food", index: 0 },
      children,
      "ArrowDown",
    );
    const picked = reducePickerKey(assigned.state, children, "Enter");
    expect(picked.effect).toEqual({ type: "assign", categoryId: "food" });
  });

  it("searches flat and highlights a parent before a same-named child", () => {
    const rows = buildPickerRows({
      categories: catalog,
      query: "food",
      parentId: "food",
      placing: false,
      selectedId: null,
      recentIds: [],
      usage: new Map(),
    });
    expect(rows.map((row) => row.name)[0]).toBe("Food");
    expect(rows.map((row) => row.name)).toContain("Transport › Food");
  });

  it("assigns a parent directly with alt enter and walks back on an empty query", () => {
    const rows = buildPickerRows({
      categories: catalog,
      query: "",
      parentId: null,
      placing: false,
      selectedId: null,
      recentIds: [],
      usage: new Map(),
    });
    const index = rows.findIndex((row) => row.name === "Food");
    const direct = reducePickerKey(
      { ...closedPicker, open: true, index },
      rows,
      "Enter",
      { alt: true },
    );
    expect(direct.effect).toEqual({ type: "assign", categoryId: "food" });
    const back = reducePickerKey(
      { ...closedPicker, open: true, parentId: "food" },
      [],
      "Backspace",
    );
    expect(back.state.parentId).toBeNull();
  });

  it("disables moving a parent that has subcategories", () => {
    const rows = buildPickerRows({
      categories: catalog,
      query: "",
      parentId: null,
      placing: false,
      selectedId: null,
      recentIds: [],
      usage: new Map(),
      mode: "parents",
      blockParentTargets: true,
    });
    expect(rows.find((row) => row.name === "Top level")?.disabled).toBe(false);
    expect(rows.find((row) => row.name === "Food")?.disabled).toBe(true);
    expect(rows.find((row) => row.name === "Food")?.hint).toBe(
      "Has subcategories",
    );
  });
});
