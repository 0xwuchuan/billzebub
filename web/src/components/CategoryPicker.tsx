import { useEffect, useRef, type RefObject } from "react";

import type { Category } from "../api";
import { CategoryChip } from "./ui/CategoryChip";

export function CategoryPicker({
  categories,
  matches,
  draftId,
  open,
  query,
  activeIndex,
  inputId,
  listId,
  searchRef,
  onOpen,
  onQuery,
  onHighlight,
  onChoose,
}: {
  categories: Category[];
  matches: Category[];
  draftId: string;
  open: boolean;
  query: string;
  activeIndex: number;
  inputId: string;
  listId: string;
  searchRef: RefObject<HTMLInputElement | null>;
  onOpen: () => void;
  onQuery: (query: string) => void;
  onHighlight: (index: number) => void;
  onChoose: (categoryId: string) => void;
}) {
  const draft = categories.find((category) => category.id === draftId) ?? null;
  const active = matches[activeIndex] ?? null;
  const activeId = active?.id ?? "";
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    if (!open || activeId === "") {
      return;
    }
    const list = listRef.current;
    const option = document.getElementById(optionId(activeId));
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
  }, [open, activeId]);
  return (
    <div className="cat-picker">
      {open ? (
        <input
          ref={searchRef}
          id={inputId}
          className="field"
          role="combobox"
          type="text"
          data-cat-search="true"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            active === null ? undefined : optionId(active.id)
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
            <CategoryChip name={draft.name} />
          )}
        </button>
      )}
      {open ? (
        matches.length === 0 ? (
          <p className="cat-picker-empty">No matching Category</p>
        ) : (
          <ul
            ref={listRef}
            className="cat-picker-list"
            id={listId}
            role="listbox"
          >
            {matches.map((category, index) => (
              <li key={category.id}>
                <button
                  id={optionId(category.id)}
                  className={`cat-picker-option${index === activeIndex ? " is-active" : ""}`}
                  type="button"
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseEnter={() => {
                    onHighlight(index);
                  }}
                  onClick={() => {
                    onChoose(category.id);
                  }}
                >
                  <CategoryChip name={category.name} />
                </button>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}

function optionId(categoryId: string): string {
  return `review-cat-option-${categoryId}`;
}
