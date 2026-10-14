import { useEffect, useRef, type RefObject } from "react";

import { highlightParts, type PickerRow } from "../lib/categoryTree";
import { CategoryChip } from "./ui/CategoryChip";

export function CategoryPicker({
  rows,
  draft,
  open,
  query,
  activeIndex,
  inputId,
  listId,
  searchRef,
  sheet,
  onOpen,
  onDismiss,
  onQuery,
  onHighlight,
  onActivate,
}: {
  rows: PickerRow[];
  draft: { name: string; parentName: string | null; archived?: boolean } | null;
  open: boolean;
  query: string;
  activeIndex: number;
  inputId: string;
  listId: string;
  searchRef: RefObject<HTMLInputElement | null>;
  sheet: boolean;
  onOpen: () => void;
  onDismiss: () => void;
  onQuery: (query: string) => void;
  onHighlight: (index: number) => void;
  onActivate: (row: PickerRow) => void;
}) {
  const active = rows[activeIndex] ?? null;
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    if (!open || active === null) {
      return;
    }
    const list = listRef.current;
    const option = document.getElementById(optionId(active.key));
    if (list === null || !(option instanceof HTMLElement)) {
      return;
    }
    const listBox = list.getBoundingClientRect();
    const optionBox = option.getBoundingClientRect();
    if (optionBox.top < listBox.top) {
      list.scrollTop -= listBox.top - optionBox.top;
    } else if (optionBox.bottom > listBox.bottom) {
      list.scrollTop += optionBox.bottom - listBox.bottom;
    }
  }, [open, active]);
  return (
    <div
      className={`cat-picker${sheet ? " is-sheet" : ""}${open ? " is-open" : ""}`}
    >
      {open && sheet ? (
        <button
          className="cat-picker-backdrop"
          type="button"
          aria-label="Close categories"
          onClick={onDismiss}
        />
      ) : null}
      <div className="cat-picker-panel">
        {open ? (
          <input
            ref={searchRef}
            id={inputId}
            className="field cat-picker-search"
            role="combobox"
            type="text"
            inputMode="search"
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            enterKeyHint="search"
            spellCheck={false}
            data-cat-search="true"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={
              active === null ? undefined : optionId(active.key)
            }
            placeholder="Search categories"
            value={query}
            onChange={(event) => {
              onQuery(event.target.value);
            }}
          />
        ) : (
          <button
            id={inputId}
            className="select cat-picker-trigger"
            type="button"
            aria-expanded="false"
            aria-controls={listId}
            onClick={onOpen}
          >
            {draft === null ? (
              "Choose Category"
            ) : (
              <CategoryChip
                name={draft.name}
                parentName={draft.parentName}
                archived={draft.archived}
              />
            )}
          </button>
        )}
        {open ? (
          rows.length === 0 ? (
            <p className="cat-picker-empty">No matching Category</p>
          ) : (
            <ul
              ref={listRef}
              className="cat-picker-list"
              id={listId}
              role="listbox"
            >
              {rows.map((row, index) => (
                <li key={row.key}>
                  <button
                    id={optionId(row.key)}
                    className={`cat-picker-option${index === activeIndex ? " is-active" : ""}${row.pinned ? " is-pinned" : ""}${row.disabled ? " is-disabled" : ""}`}
                    type="button"
                    role="option"
                    aria-selected={row.selected || index === activeIndex}
                    aria-disabled={row.disabled || undefined}
                    aria-label={row.name}
                    title={row.disabled ? (row.hint ?? undefined) : undefined}
                    disabled={row.disabled}
                    onMouseEnter={() => {
                      onHighlight(index);
                    }}
                    onClick={() => {
                      onActivate(row);
                    }}
                  >
                    {row.selected ? (
                      <span className="cat-picker-check" aria-hidden="true">
                        ✓
                      </span>
                    ) : row.childSelected ? (
                      <i className="cat-picker-dot" aria-hidden="true" />
                    ) : (
                      <span className="cat-picker-check" aria-hidden="true" />
                    )}
                    <span className="cat-picker-copy">
                      {highlightParts(rowText(row, query), query).map(
                        (part, partIndex) =>
                          part.hit ? (
                            <mark key={`${row.key}-${partIndex}`}>
                              {part.text}
                            </mark>
                          ) : (
                            <span key={`${row.key}-${partIndex}`}>
                              {part.text}
                            </span>
                          ),
                      )}
                    </span>
                    {row.hint !== null ? (
                      <span className="cat-picker-hint" aria-hidden="true">
                        {row.hint}
                      </span>
                    ) : null}
                    {row.hasChildren ? (
                      <span className="cat-picker-chevron" aria-hidden="true">
                        ›
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>
    </div>
  );
}

function optionId(key: string): string {
  return `review-cat-option-${key}`;
}

function rowText(row: PickerRow, query: string): string {
  if (row.kind === "child" && query.trim() === "") {
    return row.label;
  }
  return row.name;
}
