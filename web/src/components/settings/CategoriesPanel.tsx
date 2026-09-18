import { useState, type FormEvent } from "react";

import type { Category } from "../../api";
import { SETUP_CATEGORIES } from "../../lib/accounts";
import { Button } from "../ui/Button";

export function CategoriesPanel({
  categories,
  saving,
  onCreateCategory,
  mode = "all",
}: {
  categories: Category[];
  saving: boolean;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  mode?: "all" | "list" | "form";
}) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const ownerCategories = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  const parents = ownerCategories.filter(
    (category) => category.parent_id === null,
  );
  const suggested = SETUP_CATEGORIES.filter(
    (item) =>
      !ownerCategories.some(
        (category) => category.name.toLowerCase() === item.toLowerCase(),
      ),
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === "") {
      return;
    }
    await onCreateCategory(name.trim(), parentId === "" ? undefined : parentId);
    setName("");
  }

  return (
    <div className="stack">
      {mode !== "form" ? (
        <div className="filters settings-chips">
          {ownerCategories.map((category) => (
            <span className="chip" aria-pressed="true" key={category.id}>
              {category.parent_id === null
                ? category.name
                : `${parents.find((parent) => parent.id === category.parent_id)?.name ?? ""} / ${category.name}`}
            </span>
          ))}
          <span className="chip">Uncategorized</span>
        </div>
      ) : null}
      {mode !== "list" ? (
        <>
          {suggested.length > 0 ? (
            <div className="filters">
              {suggested.map((item) => (
                <button
                  key={item}
                  className="chip"
                  type="button"
                  disabled={saving}
                  onClick={() => {
                    void onCreateCategory(item);
                  }}
                >
                  Add {item}
                </button>
              ))}
            </div>
          ) : null}
          <form className="stack" onSubmit={(event) => void onSubmit(event)}>
            <label className="field-label">
              Category name
              <input
                className="field"
                value={name}
                placeholder="Family, Pets, Home"
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            </label>
            <label className="field-label">
              Parent (optional subcategory)
              <select
                className="select"
                value={parentId}
                onChange={(event) => {
                  setParentId(event.target.value);
                }}
              >
                <option value="">Top-level</option>
                {parents.map((parent) => (
                  <option key={parent.id} value={parent.id}>
                    {parent.name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="primary"
              type="submit"
              disabled={saving || name.trim() === ""}
            >
              {saving ? "Saving…" : "Create Category"}
            </Button>
          </form>
        </>
      ) : null}
    </div>
  );
}
