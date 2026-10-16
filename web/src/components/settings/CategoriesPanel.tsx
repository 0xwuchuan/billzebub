import { useEffect, useRef, useState, type FormEvent } from "react";

import type { Category, Transaction } from "../../api";
import { SETUP_CATEGORIES } from "../../lib/accounts";
import {
  buildPickerRows,
  categorySpend,
  categoryUsage,
  childCategories,
  closedPicker,
  draftFromCategory,
  hasChildCategories,
  parentCategories,
  reducePickerKey,
  siblingNameTaken,
  type PickerState,
} from "../../lib/categoryTree";
import { centsToMoney, formatUnsigned } from "../../lib/money";
import { CategoryPicker } from "../CategoryPicker";
import { Button } from "../ui/Button";
import { CategoryChip } from "../ui/CategoryChip";

export type CategoryPatch = {
  name?: string;
  parent_id?: string | null;
  active?: boolean;
};

export function CategoriesPanel({
  categories,
  transactions = [],
  month,
  saving,
  onCreateCategory,
  onUpdateCategory,
  mode = "all",
}: {
  categories: Category[];
  transactions?: Transaction[] | undefined;
  month?: string | undefined;
  saving: boolean;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  onUpdateCategory?:
    ((category: Category, patch: CategoryPatch) => Promise<void>) | undefined;
  mode?: "all" | "list" | "form";
}) {
  const ownerCategories = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );
  const parents = ownerCategories.filter(
    (category) => category.parent_id === null,
  );
  if (mode === "form") {
    return (
      <CategoryForm
        categories={categories}
        parents={parents}
        ownerCategories={ownerCategories}
        saving={saving}
        onCreateCategory={onCreateCategory}
      />
    );
  }
  return (
    <CategoryTree
      categories={categories}
      transactions={transactions}
      month={month}
      saving={saving}
      onCreateCategory={onCreateCategory}
      onUpdateCategory={onUpdateCategory}
    />
  );
}

function CategoryForm({
  categories,
  parents,
  ownerCategories,
  saving,
  onCreateCategory,
}: {
  categories: Category[];
  parents: Category[];
  ownerCategories: Category[];
  saving: boolean;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const suggested = SETUP_CATEGORIES.filter(
    (item) =>
      !ownerCategories.some(
        (category) => category.name.toLowerCase() === item.toLowerCase(),
      ),
  );
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      name.trim() === "" ||
      siblingNameTaken(categories, name, parentId === "" ? null : parentId)
    ) {
      return;
    }
    await onCreateCategory(name.trim(), parentId === "" ? undefined : parentId);
    setName("");
  }
  return (
    <div className="stack">
      <div className="settings-taxonomy">
        {ownerCategories.map((category) => (
          <span className="settings-taxonomy-item" key={category.id}>
            <CategoryChip name={category.name} />
          </span>
        ))}
        <CategoryChip name="Uncategorized" />
      </div>
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
            type="text"
            value={name}
            autoComplete="off"
            autoCapitalize="words"
            enterKeyHint="done"
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
    </div>
  );
}

function CategoryTree({
  categories,
  transactions,
  month,
  saving,
  onCreateCategory,
  onUpdateCategory,
}: {
  categories: Category[];
  transactions: Transaction[];
  month?: string | undefined;
  saving: boolean;
  onCreateCategory: (name: string, parentId?: string) => Promise<void>;
  onUpdateCategory?:
    ((category: Category, patch: CategoryPatch) => Promise<void>) | undefined;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [creatingParentId, setCreatingParentId] = useState<
    string | null | undefined
  >(undefined);
  const [error, setError] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);
  const [moveId, setMoveId] = useState<string | null>(null);
  const [archiveId, setArchiveId] = useState<string | null>(null);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const usage = categoryUsage(transactions);
  const period = month ?? new Date().toISOString().slice(0, 7);
  const spend = categorySpend(transactions, period, categories);
  const parents = parentCategories(categories);
  const archived = categories.filter(
    (category) => !category.active && category.name !== "Uncategorized",
  );
  const moving = categories.find((category) => category.id === moveId) ?? null;

  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const root = rootRef.current;
      if (
        root === null ||
        !(event.target instanceof Node) ||
        !root.contains(event.target)
      ) {
        return;
      }
      if (isField(event.target)) {
        return;
      }
      if (event.key === "n" && !event.shiftKey) {
        event.preventDefault();
        setCreatingParentId(null);
        setError("");
      }
      if (event.key === "N" && focusId !== null) {
        const parent = categories.find((category) => category.id === focusId);
        if (parent !== undefined && parent.parent_id === null) {
          event.preventDefault();
          setCreatingParentId(parent.id);
          setError("");
        }
      }
    }
    const node = rootRef.current;
    node?.addEventListener("keydown", onKey);
    return () => {
      node?.removeEventListener("keydown", onKey);
    };
  }, [categories, focusId]);

  async function commitName(
    category: Category | null,
    parentId: string | null,
  ) {
    const name = draftName.trim();
    if (name === "") {
      setCreatingParentId(undefined);
      setEditingId(null);
      return;
    }
    if (siblingNameTaken(categories, name, parentId, category?.id)) {
      setError("A category with this name already exists at this level.");
      return;
    }
    setError("");
    if (category === null) {
      await onCreateCategory(name, parentId ?? undefined);
      setCreatingParentId(undefined);
      setDraftName("");
      return;
    }
    await onUpdateCategory?.(category, { name });
    setEditingId(null);
    setDraftName("");
  }

  return (
    <div className="cat-admin" ref={rootRef} tabIndex={-1}>
      <p className="muted cat-admin-hint">
        N adds a category. Shift+N on a parent adds a subcategory.
      </p>
      {error !== "" ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
      <ul className="cat-admin-list">
        {parents.map((category) => (
          <li key={category.id}>
            <AdminRow
              category={category}
              categories={categories}
              usage={usage}
              spend={spendCents(spend, category.id)}
              editing={editingId === category.id}
              draftName={draftName}
              focused={focusId === category.id}
              saving={saving}
              onFocus={() => {
                setFocusId(category.id);
              }}
              onDraft={setDraftName}
              onEdit={() => {
                setEditingId(category.id);
                setDraftName(category.name);
                setError("");
              }}
              onCommit={() => {
                void commitName(category, category.parent_id);
              }}
              onCancel={() => {
                setEditingId(null);
                setDraftName("");
                setError("");
              }}
              onMenu={() => {
                setMenuId((current) =>
                  current === category.id ? null : category.id,
                );
              }}
              menuOpen={menuId === category.id}
              onRename={() => {
                setMenuId(null);
                setEditingId(category.id);
                setDraftName(category.name);
              }}
              onMove={() => {
                setMenuId(null);
                setMoveId(category.id);
              }}
              onArchive={() => {
                setMenuId(null);
                setArchiveId(category.id);
              }}
            />
            <ul className="cat-admin-children">
              {childCategories(categories, category.id).map((child) => (
                <li key={child.id}>
                  <AdminRow
                    category={child}
                    categories={categories}
                    usage={usage}
                    spend={spendCents(spend, child.id)}
                    editing={editingId === child.id}
                    draftName={draftName}
                    focused={focusId === child.id}
                    saving={saving}
                    onFocus={() => {
                      setFocusId(child.id);
                    }}
                    onDraft={setDraftName}
                    onEdit={() => {
                      setEditingId(child.id);
                      setDraftName(child.name);
                      setError("");
                    }}
                    onCommit={() => {
                      void commitName(child, child.parent_id);
                    }}
                    onCancel={() => {
                      setEditingId(null);
                      setDraftName("");
                      setError("");
                    }}
                    onMenu={() => {
                      setMenuId((current) =>
                        current === child.id ? null : child.id,
                      );
                    }}
                    menuOpen={menuId === child.id}
                    onRename={() => {
                      setMenuId(null);
                      setEditingId(child.id);
                      setDraftName(child.name);
                    }}
                    onMove={() => {
                      setMenuId(null);
                      setMoveId(child.id);
                    }}
                    onArchive={() => {
                      setMenuId(null);
                      setArchiveId(child.id);
                    }}
                  />
                </li>
              ))}
              {creatingParentId === category.id ? (
                <li>
                  <NameField
                    value={draftName}
                    onChange={setDraftName}
                    onCommit={() => {
                      void commitName(null, category.id);
                    }}
                    onCancel={() => {
                      setCreatingParentId(undefined);
                      setDraftName("");
                    }}
                  />
                </li>
              ) : null}
            </ul>
          </li>
        ))}
        {creatingParentId === null ? (
          <li>
            <NameField
              value={draftName}
              onChange={setDraftName}
              onCommit={() => {
                void commitName(null, null);
              }}
              onCancel={() => {
                setCreatingParentId(undefined);
                setDraftName("");
              }}
            />
          </li>
        ) : null}
      </ul>
      <CategoryChip name="Uncategorized" />
      {archived.length > 0 ? (
        <details
          className="cat-admin-archived"
          open={archivedOpen}
          onToggle={(event) => {
            setArchivedOpen(event.currentTarget.open);
          }}
        >
          <summary>Archived ({archived.length})</summary>
          <ul className="cat-admin-list">
            {archived.map((category) => (
              <li key={category.id}>
                <span className="cat-admin-row">
                  <CategoryChip name={category.name} archived />
                  <Button
                    variant="ghost"
                    disabled={saving}
                    onClick={() => {
                      void onUpdateCategory?.(category, { active: true });
                    }}
                  >
                    Un-archive
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {archiveId !== null ? (
        <ArchiveConfirm
          category={categories.find((item) => item.id === archiveId) ?? null}
          count={childCategories(categories, archiveId).length}
          saving={saving}
          onCancel={() => {
            setArchiveId(null);
          }}
          onConfirm={() => {
            const category = categories.find((item) => item.id === archiveId);
            if (category !== undefined) {
              void onUpdateCategory?.(category, { active: false });
            }
            setArchiveId(null);
          }}
        />
      ) : null}
      {moving !== null ? (
        <MovePicker
          categories={categories}
          moving={moving}
          onClose={() => {
            setMoveId(null);
          }}
          onMove={(parentId) => {
            void onUpdateCategory?.(moving, { parent_id: parentId });
            setMoveId(null);
          }}
        />
      ) : null}
    </div>
  );
}

function AdminRow({
  category,
  categories,
  usage,
  spend,
  editing,
  draftName,
  focused,
  saving,
  onFocus,
  onDraft,
  onEdit,
  onCommit,
  onCancel,
  onMenu,
  menuOpen,
  onRename,
  onMove,
  onArchive,
}: {
  category: Category;
  categories: Category[];
  usage: ReadonlyMap<string, number>;
  spend: number;
  editing: boolean;
  draftName: string;
  focused: boolean;
  saving: boolean;
  onFocus: () => void;
  onDraft: (value: string) => void;
  onEdit: () => void;
  onCommit: () => void;
  onCancel: () => void;
  onMenu: () => void;
  menuOpen: boolean;
  onRename: () => void;
  onMove: () => void;
  onArchive: () => void;
}) {
  const parent = categories.find((item) => item.id === category.parent_id);
  const count = usage.get(category.id) ?? usage.get(category.name) ?? 0;
  return (
    <div className={`cat-admin-row${focused ? " is-focused" : ""}`}>
      {editing ? (
        <NameField
          value={draftName}
          onChange={onDraft}
          onCommit={onCommit}
          onCancel={onCancel}
        />
      ) : (
        <button
          className="cat-admin-name"
          type="button"
          onFocus={onFocus}
          onDoubleClick={onEdit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onEdit();
            }
          }}
        >
          <CategoryChip
            name={category.name}
            parentName={parent?.name ?? null}
          />
        </button>
      )}
      <span className="muted cat-admin-meta">
        {count} · {formatUnsigned(centsToMoney(spend, "SGD"))}
      </span>
      <Button variant="ghost" disabled={saving} onClick={onMenu}>
        Actions
      </Button>
      {menuOpen ? (
        <div className="cat-admin-menu" role="menu">
          <button type="button" onClick={onRename}>
            Rename
          </button>
          <button type="button" onClick={onMove}>
            Move to…
          </button>
          <button type="button" onClick={onArchive}>
            Archive
          </button>
        </div>
      ) : null}
    </div>
  );
}

function NameField({
  value,
  onChange,
  onCommit,
  onCancel,
}: {
  value: string;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <input
      ref={ref}
      className="field"
      type="text"
      value={value}
      aria-label="Category name"
      onChange={(event) => {
        onChange(event.target.value);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          onCommit();
        }
        if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
      }}
    />
  );
}

function ArchiveConfirm({
  category,
  count,
  saving,
  onCancel,
  onConfirm,
}: {
  category: Category | null;
  count: number;
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (category === null) {
    return null;
  }
  const message =
    count > 0
      ? `Archive ${category.name} and its ${count} ${count === 1 ? "subcategory" : "subcategories"}?`
      : `Archive ${category.name}?`;
  return (
    <div className="cat-admin-confirm" role="alertdialog" aria-label={message}>
      <p>{message}</p>
      <Button variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
      <Button variant="primary" disabled={saving} onClick={onConfirm}>
        Archive
      </Button>
    </div>
  );
}

function MovePicker({
  categories,
  moving,
  onClose,
  onMove,
}: {
  categories: Category[];
  moving: Category;
  onClose: () => void;
  onMove: (parentId: string | null) => void;
}) {
  const sheet = window.matchMedia("(max-width: 52rem)").matches;
  const searchRef = useRef<HTMLInputElement>(null);
  const [picker, setPicker] = useState<PickerState>({
    ...closedPicker,
    open: true,
  });
  useEffect(() => {
    searchRef.current?.focus();
  }, []);
  const blocked = hasChildCategories(categories, moving.id);
  const rows = buildPickerRows({
    categories: categories.filter((category) => category.id !== moving.id),
    query: picker.query,
    parentId: null,
    placing: false,
    selectedId: moving.parent_id,
    recentIds: [],
    usage: new Map(),
    mode: "parents",
    blockParentTargets: blocked,
  });
  return (
    <div
      className="cat-admin-move"
      role="dialog"
      aria-label={`Move ${moving.name}`}
    >
      <p>Move {moving.name}</p>
      <CategoryPicker
        rows={rows}
        draft={draftFromCategory(categories, moving.id)}
        open
        query={picker.query}
        activeIndex={picker.index}
        inputId={`move-${moving.id}`}
        listId={`move-list-${moving.id}`}
        searchRef={searchRef}
        sheet={sheet}
        onOpen={() => undefined}
        onDismiss={onClose}
        onQuery={(query) => {
          setPicker((current) => ({ ...current, query, index: 0 }));
        }}
        onHighlight={(index) => {
          setPicker((current) => ({ ...current, index }));
        }}
        onActivate={(row) => {
          const next = reducePickerKey(
            {
              ...picker,
              index: rows.findIndex((item) => item.key === row.key),
            },
            rows,
            "Enter",
          );
          if (next.effect?.type === "assign" || row.kind === "place") {
            onMove(row.categoryId);
            return;
          }
          setPicker(next.state);
        }}
      />
      <Button variant="ghost" onClick={onClose}>
        Cancel
      </Button>
    </div>
  );
}

function spendCents(
  groups: ReturnType<typeof categorySpend>,
  categoryId: string,
): number {
  for (const group of groups) {
    if (group.id === categoryId) {
      return group.cents;
    }
    const child = group.children.find((item) => item.categoryId === categoryId);
    if (child !== undefined) {
      return child.cents;
    }
  }
  return 0;
}

function isField(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" || target.tagName === "TEXTAREA")
  );
}
