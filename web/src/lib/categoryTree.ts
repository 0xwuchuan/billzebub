import type { Category, Transaction } from "../api";
import { amountToCents } from "./money";
import { inPeriod, isExpense, isProvisional } from "./workspace";

export const PATH_MARK = " › ";

export type PickerRowKind =
  "recent" | "parent" | "child" | "just" | "back" | "create" | "place";

export type PickerRow = {
  key: string;
  name: string;
  kind: PickerRowKind;
  categoryId: string | null;
  label: string;
  parentLabel: string | null;
  hint: string | null;
  hasChildren: boolean;
  selected: boolean;
  childSelected: boolean;
  disabled: boolean;
  pinned: boolean;
};

export type PickerState = {
  open: boolean;
  query: string;
  index: number;
  parentId: string | null;
  placing: boolean;
};

export const closedPicker: PickerState = {
  open: false,
  query: "",
  index: 0,
  parentId: null,
  placing: false,
};

export type PickerEffect =
  | { type: "assign"; categoryId: string }
  | { type: "close" }
  | { type: "create"; name: string; parentId: string | null };

export type SpendChild = {
  id: string;
  name: string;
  cents: number;
  provisional: boolean;
  unsorted: boolean;
  categoryId: string | null;
};

export type SpendGroup = {
  id: string;
  name: string;
  cents: number;
  directCents: number;
  provisional: boolean;
  children: SpendChild[];
};

export function activeCatalog(categories: Category[]): Category[] {
  return categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
}

export function parentCategories(categories: Category[]): Category[] {
  return activeCatalog(categories)
    .filter((category) => category.parent_id === null)
    .sort((left, right) => left.name.localeCompare(right.name));
}

export function childCategories(
  categories: Category[],
  parentId: string,
): Category[] {
  return activeCatalog(categories)
    .filter((category) => category.parent_id === parentId)
    .sort((left, right) => left.name.localeCompare(right.name));
}

export function categoryById(
  categories: Category[],
  id: string | null,
): Category | undefined {
  if (id === null || id === "") {
    return undefined;
  }
  return categories.find((category) => category.id === id);
}

export function hasChildCategories(
  categories: Category[],
  categoryId: string,
): boolean {
  return categories.some(
    (category) => category.active && category.parent_id === categoryId,
  );
}

export function siblingNameTaken(
  categories: Category[],
  name: string,
  parentId: string | null,
  exceptId?: string,
): boolean {
  const folded = fold(name);
  if (folded === "") {
    return false;
  }
  return categories.some(
    (category) =>
      category.id !== exceptId &&
      category.parent_id === parentId &&
      fold(category.name) === folded,
  );
}

export function categoryUsage(
  transactions: Transaction[],
): Map<string, number> {
  const usage = new Map<string, number>();
  for (const transaction of transactions) {
    if (!isExpense(transaction)) {
      continue;
    }
    for (const split of transaction.category_splits) {
      if (split.name === "Uncategorized") {
        continue;
      }
      usage.set(split.id, (usage.get(split.id) ?? 0) + 1);
      usage.set(split.name, (usage.get(split.name) ?? 0) + 1);
    }
  }
  return usage;
}

export function recentLeafIds(
  transactions: Transaction[],
  categories: Category[],
  limit = 3,
): string[] {
  const leaves: string[] = [];
  const ordered = [...transactions].sort((left, right) =>
    left.effective_date < right.effective_date ? 1 : -1,
  );
  for (const transaction of ordered) {
    for (const split of transaction.category_splits) {
      const category =
        categoryById(categories, split.id) ??
        categories.find((item) => item.active && item.name === split.name);
      if (category === undefined || !category.active) {
        continue;
      }
      if (category.name === "Uncategorized") {
        continue;
      }
      if (hasChildCategories(categories, category.id)) {
        continue;
      }
      if (leaves.includes(category.id)) {
        continue;
      }
      leaves.push(category.id);
      if (leaves.length >= limit) {
        return leaves;
      }
    }
  }
  return leaves;
}

export function chipParts(
  categories: Category[],
  categoryId: string | null,
  fallbackName: string,
): { name: string; parentName: string | null; archived: boolean } {
  const category =
    categoryById(categories, categoryId) ??
    categories.find((item) => item.name === fallbackName);
  if (category === undefined) {
    return { name: fallbackName, parentName: null, archived: false };
  }
  const parent = categoryById(categories, category.parent_id);
  return {
    name: category.name,
    parentName: parent?.name ?? null,
    archived: !category.active,
  };
}

export function draftFromCategory(
  categories: Category[],
  categoryId: string,
): { name: string; parentName: string | null; archived: boolean } | null {
  const category = categories.find((item) => item.id === categoryId);
  if (category === undefined) {
    return null;
  }
  const parent =
    category.parent_id === null
      ? null
      : (categories.find((item) => item.id === category.parent_id) ?? null);
  return {
    name: category.name,
    parentName: parent?.name ?? null,
    archived: !category.active,
  };
}

export function buildPickerRows(input: {
  categories: Category[];
  query: string;
  parentId: string | null;
  placing: boolean;
  selectedId: string | null;
  recentIds: string[];
  usage: ReadonlyMap<string, number>;
  mode?: "assign" | "parents";
  allowCreate?: boolean;
  blockParentTargets?: boolean;
}): PickerRow[] {
  const mode = input.mode ?? "assign";
  const catalog = activeCatalog(input.categories);
  const parents = catalog.filter((category) => category.parent_id === null);
  const needle = fold(input.query);
  const selected = categoryById(input.categories, input.selectedId);

  const scoreParent = (category: Category) =>
    parentUsage(category, input.usage, catalog);

  if (input.placing) {
    const rows: PickerRow[] = [
      placeRow("Top level", null, input.parentId === null),
    ];
    for (const parent of sortByUsage(parents, input.usage, scoreParent)) {
      rows.push(placeRow(parent.name, parent.id, input.parentId === parent.id));
    }
    return rows;
  }

  if (needle !== "") {
    const parentRows = sortByUsage(
      parents.filter((category) => fold(category.name).includes(needle)),
      input.usage,
      scoreParent,
    ).map((category) =>
      parentRow(category, input, selected, childCount(catalog, category.id)),
    );
    const childRows = sortByUsage(
      catalog.filter((category) => {
        if (category.parent_id === null) {
          return false;
        }
        const parent = categoryById(catalog, category.parent_id);
        const path = `${parent?.name ?? ""} ${PATH_MARK} ${category.name}`;
        return (
          fold(category.name).includes(needle) || fold(path).includes(needle)
        );
      }),
      input.usage,
      (category) =>
        input.usage.get(category.id) ?? input.usage.get(category.name) ?? 0,
    ).map((category) => {
      const parent = categoryById(catalog, category.parent_id);
      return childRow(category, parent?.name ?? "", input.selectedId);
    });
    const matches = [...parentRows, ...childRows];
    if (
      matches.length === 0 &&
      input.allowCreate === true &&
      mode === "assign"
    ) {
      return [createRow(input.query.trim())];
    }
    return matches;
  }

  if (mode === "parents") {
    return [
      placeRow("Top level", null, false),
      ...sortByUsage(parents, input.usage, scoreParent).map((category) => {
        const blocked = input.blockParentTargets === true;
        return {
          ...parentRow(
            category,
            input,
            selected,
            childCount(catalog, category.id),
          ),
          disabled: blocked,
          hint: blocked ? "Has subcategories" : null,
          hasChildren: false,
        };
      }),
    ];
  }

  if (input.parentId !== null) {
    const parent = categoryById(catalog, input.parentId);
    if (parent === undefined) {
      return [];
    }
    const children = sortByUsage(
      catalog.filter((category) => category.parent_id === parent.id),
      input.usage,
      (category) =>
        input.usage.get(category.id) ?? input.usage.get(category.name) ?? 0,
    );
    return [
      {
        key: `back-${parent.id}`,
        name: "Back",
        kind: "back",
        categoryId: null,
        label: "Back",
        parentLabel: null,
        hint: null,
        hasChildren: false,
        selected: false,
        childSelected: false,
        disabled: false,
        pinned: false,
      },
      {
        key: `just-${parent.id}`,
        name: `Just ${parent.name}`,
        kind: "just",
        categoryId: parent.id,
        label: `Just ${parent.name}`,
        parentLabel: null,
        hint: null,
        hasChildren: false,
        selected: input.selectedId === parent.id,
        childSelected: false,
        disabled: false,
        pinned: true,
      },
      ...children.map((category) =>
        childRow(category, parent.name, input.selectedId),
      ),
    ];
  }

  const recent = input.recentIds
    .map((id) => categoryById(catalog, id))
    .filter((category): category is Category => category !== undefined)
    .slice(0, 3)
    .map((category) => {
      const parent = categoryById(catalog, category.parent_id);
      if (parent === undefined) {
        return {
          ...parentRow(category, input, selected, 0),
          key: `recent-${category.id}`,
          kind: "recent" as const,
          hasChildren: false,
        };
      }
      return {
        ...childRow(category, parent.name, input.selectedId),
        key: `recent-${category.id}`,
        kind: "recent" as const,
      };
    });
  const parentRows = sortByUsage(parents, input.usage, scoreParent).map(
    (category) =>
      parentRow(category, input, selected, childCount(catalog, category.id)),
  );
  return [...recent, ...parentRows];
}

export function reducePickerKey(
  state: PickerState,
  rows: PickerRow[],
  key: string,
  options: { alt?: boolean } = {},
): { state: PickerState; effect: PickerEffect | null } {
  const current = rows[state.index] ?? null;
  if (key === "Escape") {
    return { state: closedPicker, effect: { type: "close" } };
  }
  if (key === "ArrowDown") {
    return {
      state: {
        ...state,
        index: Math.min(Math.max(rows.length - 1, 0), state.index + 1),
      },
      effect: null,
    };
  }
  if (key === "ArrowUp") {
    return {
      state: { ...state, index: Math.max(0, state.index - 1) },
      effect: null,
    };
  }
  if (key === "ArrowLeft" || (key === "Backspace" && state.query === "")) {
    if (state.placing) {
      return { state: { ...state, placing: false, index: 0 }, effect: null };
    }
    if (state.parentId !== null) {
      return {
        state: { ...state, parentId: null, index: 0 },
        effect: null,
      };
    }
    return { state, effect: null };
  }
  if (key === "ArrowRight") {
    if (
      current?.kind === "parent" &&
      current.hasChildren &&
      !current.disabled
    ) {
      return {
        state: {
          ...state,
          parentId: current.categoryId,
          query: "",
          index: 0,
          placing: false,
        },
        effect: null,
      };
    }
    return { state, effect: null };
  }
  if (key !== "Enter" || current === null || current.disabled) {
    return { state, effect: null };
  }
  if (
    options.alt === true &&
    current.categoryId !== null &&
    (current.kind === "parent" || current.kind === "recent")
  ) {
    return {
      state: closedPicker,
      effect: { type: "assign", categoryId: current.categoryId },
    };
  }
  if (current.kind === "parent" && current.hasChildren) {
    return {
      state: {
        ...state,
        parentId: current.categoryId,
        query: "",
        index: 0,
        placing: false,
      },
      effect: null,
    };
  }
  if (current.kind === "create") {
    return { state: { ...state, placing: true, index: 0 }, effect: null };
  }
  if (current.kind === "place") {
    return {
      state: closedPicker,
      effect: {
        type: "create",
        name: state.query.trim(),
        parentId: current.categoryId,
      },
    };
  }
  if (current.kind === "back") {
    return {
      state: { ...state, parentId: null, index: 0 },
      effect: null,
    };
  }
  if (current.categoryId === null) {
    return { state, effect: null };
  }
  return {
    state: closedPicker,
    effect: { type: "assign", categoryId: current.categoryId },
  };
}

export function highlightParts(
  label: string,
  query: string,
): Array<{ text: string; hit: boolean }> {
  const needle = query.trim();
  if (needle === "") {
    return [{ text: label, hit: false }];
  }
  const folded = label.toLowerCase();
  const target = needle.toLowerCase();
  const index = folded.indexOf(target);
  if (index < 0) {
    return [{ text: label, hit: false }];
  }
  return [
    { text: label.slice(0, index), hit: false },
    { text: label.slice(index, index + needle.length), hit: true },
    { text: label.slice(index + needle.length), hit: false },
  ].filter((part) => part.text !== "");
}

export function categorySpend(
  transactions: Transaction[],
  yearMonth: string,
  categories: Category[] = [],
): SpendGroup[] {
  const buckets = new Map<
    string,
    {
      name: string;
      direct: number;
      provisional: boolean;
      children: Map<
        string,
        {
          name: string;
          cents: number;
          provisional: boolean;
          categoryId: string;
        }
      >;
    }
  >();

  for (const transaction of transactions) {
    if (!isExpense(transaction) || !inPeriod(transaction, yearMonth)) {
      continue;
    }
    const provisional = isProvisional(transaction);
    if (provisional && !hasSpendCategory(transaction)) {
      continue;
    }
    const cents = provisional
      ? provisionalCents(transaction)
      : Math.abs(amountToCents(transaction.posted_amount.amount));
    for (const split of transaction.category_splits) {
      if (split.name === "Uncategorized") {
        continue;
      }
      const share =
        transaction.category_splits.length === 1
          ? cents
          : Math.abs(amountToCents(split.amount.amount));
      const resolved = resolveSplit(categories, split.id, split.name);
      const parent =
        resolved?.parent_id != null
          ? categoryById(categories, resolved.parent_id)
          : undefined;
      const groupKey = parent?.id ?? resolved?.id ?? split.name;
      const groupName = parent?.name ?? resolved?.name ?? split.name;
      const bucket = buckets.get(groupKey) ?? {
        name: groupName,
        direct: 0,
        provisional: false,
        children: new Map(),
      };
      if (parent !== undefined && resolved !== undefined) {
        const child = bucket.children.get(resolved.id) ?? {
          name: resolved.name,
          cents: 0,
          provisional: false,
          categoryId: resolved.id,
        };
        child.cents += share;
        child.provisional = child.provisional || provisional;
        bucket.children.set(resolved.id, child);
      } else {
        bucket.direct += share;
      }
      bucket.provisional = bucket.provisional || provisional;
      buckets.set(groupKey, bucket);
    }
  }

  const groups: SpendGroup[] = [];
  for (const [id, bucket] of buckets) {
    const catalogChildren = categories.some(
      (category) => category.active && category.parent_id === id,
    );
    const children: SpendChild[] = [...bucket.children.values()]
      .filter((child) => child.cents > 0)
      .sort(
        (left, right) =>
          right.cents - left.cents || left.name.localeCompare(right.name),
      )
      .map((child) => ({
        id: child.categoryId,
        name: child.name,
        cents: child.cents,
        provisional: child.provisional,
        unsorted: false,
        categoryId: child.categoryId,
      }));
    if (bucket.direct > 0 && (catalogChildren || children.length > 0)) {
      children.push({
        id: `${id}:unsorted`,
        name: `${bucket.name} (unsorted)`,
        cents: bucket.direct,
        provisional:
          bucket.provisional && children.every((child) => !child.provisional),
        unsorted: true,
        categoryId: id,
      });
    }
    const childTotal = children.reduce((sum, child) => sum + child.cents, 0);
    const cents = children.length > 0 ? childTotal : bucket.direct;
    if (cents <= 0) {
      continue;
    }
    groups.push({
      id,
      name: bucket.name,
      cents,
      directCents: bucket.direct,
      provisional: bucket.provisional,
      children:
        children.length > 0 && (catalogChildren || bucket.children.size > 0)
          ? children
          : [],
    });
  }
  return groups.sort(
    (left, right) =>
      right.cents - left.cents || left.name.localeCompare(right.name),
  );
}

export function spendReconciles(group: SpendGroup): boolean {
  if (group.children.length === 0) {
    return group.cents === group.directCents;
  }
  const summed = group.children.reduce((sum, child) => sum + child.cents, 0);
  return group.cents === summed;
}

function hasSpendCategory(transaction: Transaction): boolean {
  return transaction.category_splits.some(
    (split) => split.name !== "Uncategorized",
  );
}

function provisionalCents(transaction: Transaction): number {
  const authorized = transaction.authorized_amount;
  if (authorized === null) {
    return Math.abs(amountToCents(transaction.posted_amount.amount));
  }
  return Math.abs(amountToCents(authorized.amount));
}

function resolveSplit(
  categories: Category[],
  splitId: string,
  splitName: string,
): Category | undefined {
  const byId = categoryById(categories, splitId);
  if (byId !== undefined) {
    return byId;
  }
  const fixtureId = splitId.endsWith("-split")
    ? splitId.slice(0, -"-split".length)
    : splitId;
  const byFixtureId = categoryById(categories, fixtureId);
  if (byFixtureId !== undefined) {
    return byFixtureId;
  }
  const named = categories.filter((category) => category.name === splitName);
  return named.length === 1 ? named[0] : undefined;
}

function fold(value: string): string {
  return value.trim().toLowerCase();
}

function childCount(categories: Category[], parentId: string): number {
  return categories.filter((category) => category.parent_id === parentId)
    .length;
}

function parentUsage(
  category: Category,
  usage: ReadonlyMap<string, number>,
  categories: Category[],
): number {
  const own = usage.get(category.id) ?? usage.get(category.name) ?? 0;
  return categories
    .filter((item) => item.parent_id === category.id)
    .reduce(
      (sum, child) => sum + (usage.get(child.id) ?? usage.get(child.name) ?? 0),
      own,
    );
}

function sortByUsage(
  categories: Category[],
  usage: ReadonlyMap<string, number>,
  score: (category: Category) => number,
): Category[] {
  return [...categories].sort(
    (left, right) =>
      score(right) - score(left) || left.name.localeCompare(right.name),
  );
}

function parentRow(
  category: Category,
  input: {
    selectedId: string | null;
    categories: Category[];
    usage: ReadonlyMap<string, number>;
  },
  selected: Category | undefined,
  count: number,
): PickerRow {
  return {
    key: `parent-${category.id}`,
    name: category.name,
    kind: "parent",
    categoryId: category.id,
    label: category.name,
    parentLabel: null,
    hint: count > 0 ? String(count) : null,
    hasChildren: count > 0,
    selected: input.selectedId === category.id,
    childSelected: selected?.parent_id === category.id,
    disabled: false,
    pinned: false,
  };
}

function childRow(
  category: Category,
  parentName: string,
  selectedId: string | null,
): PickerRow {
  const label = `${parentName}${PATH_MARK}${category.name}`;
  return {
    key: `child-${category.id}`,
    name: label,
    kind: "child",
    categoryId: category.id,
    label: category.name,
    parentLabel: parentName,
    hint: null,
    hasChildren: false,
    selected: selectedId === category.id,
    childSelected: false,
    disabled: false,
    pinned: false,
  };
}

function createRow(query: string): PickerRow {
  return {
    key: "create",
    name: `Create "${query}"`,
    kind: "create",
    categoryId: null,
    label: `Create "${query}"`,
    parentLabel: null,
    hint: null,
    hasChildren: false,
    selected: false,
    childSelected: false,
    disabled: false,
    pinned: false,
  };
}

function placeRow(
  label: string,
  categoryId: string | null,
  selected: boolean,
): PickerRow {
  return {
    key: `place-${categoryId ?? "root"}`,
    name: label,
    kind: "place",
    categoryId,
    label,
    parentLabel: null,
    hint: null,
    hasChildren: false,
    selected,
    childSelected: false,
    disabled: false,
    pinned: categoryId === null,
  };
}
