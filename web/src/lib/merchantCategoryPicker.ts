import type { Category } from "../api";

/**
 * Parent → child rows for the merchant-group field.
 * PR #59's shared picker is not on main yet. This keeps the same drill:
 * P opens it, a parent with children drills in, and "Just {Parent}" assigns
 * the parent. Swap the call site to CategoryPicker once that PR lands.
 */

export type MerchantPickerRow = {
  key: string;
  name: string;
  kind: "parent" | "child" | "just" | "back";
  categoryId: string | null;
  hasChildren: boolean;
};

export function merchantPickerRows(
  categories: Category[],
  query: string,
  parentId: string | null,
): MerchantPickerRow[] {
  const catalog = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  const parents = catalog
    .filter((category) => category.parent_id === null)
    .sort((left, right) => left.name.localeCompare(right.name));
  const needle = query.trim().toLocaleLowerCase();
  if (needle !== "") {
    const parentHits = parents
      .filter((category) => category.name.toLocaleLowerCase().includes(needle))
      .map((category) => parentRow(category, catalog));
    const childHits = catalog
      .filter((category) => category.parent_id !== null)
      .filter((category) => {
        const parent = catalog.find((item) => item.id === category.parent_id);
        const path =
          `${parent?.name ?? ""} ${category.name}`.toLocaleLowerCase();
        return (
          category.name.toLocaleLowerCase().includes(needle) ||
          path.includes(needle)
        );
      })
      .sort((left, right) => left.name.localeCompare(right.name))
      .map((category) => {
        const parent = catalog.find((item) => item.id === category.parent_id);
        return childRow(category, parent?.name ?? "");
      });
    return [...parentHits, ...childHits];
  }
  if (parentId !== null) {
    const parent = catalog.find((category) => category.id === parentId);
    if (parent === undefined) {
      return [];
    }
    const children = catalog
      .filter((category) => category.parent_id === parent.id)
      .sort((left, right) => left.name.localeCompare(right.name));
    return [
      {
        key: `back-${parent.id}`,
        name: `← ${parent.name}`,
        kind: "back",
        categoryId: null,
        hasChildren: false,
      },
      {
        key: `just-${parent.id}`,
        name: `Just ${parent.name}`,
        kind: "just",
        categoryId: parent.id,
        hasChildren: false,
      },
      ...children.map((category) => childRow(category, parent.name)),
    ];
  }
  return parents.map((category) => parentRow(category, catalog));
}

function parentRow(category: Category, catalog: Category[]): MerchantPickerRow {
  const hasChildren = catalog.some((item) => item.parent_id === category.id);
  return {
    key: category.id,
    name: category.name,
    kind: "parent",
    categoryId: hasChildren ? null : category.id,
    hasChildren,
  };
}

function childRow(category: Category, parentName: string): MerchantPickerRow {
  return {
    key: category.id,
    name:
      parentName === "" ? category.name : `${parentName} › ${category.name}`,
    kind: "child",
    categoryId: category.id,
    hasChildren: false,
  };
}
