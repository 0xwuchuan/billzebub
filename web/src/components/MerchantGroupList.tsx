import { useEffect, useId, useRef, useState, type RefObject } from "react";

import type { Category } from "../api";
import { dayMonthLabel } from "../lib/labels";
import { merchantPickerRows } from "../lib/merchantCategoryPicker";
import {
  remembersByDefault,
  type MerchantGroupMember,
  type MerchantGroupView,
} from "../lib/merchantGroups";
import { amountToCents, centsToMoney, formatUnsigned } from "../lib/money";
import { Button } from "./ui/Button";
import { MoneyText } from "./MoneyText";

export type MerchantUndo = {
  label: string;
  categoryName: string;
  count: number;
  remember: boolean;
};

export type MerchantApplyRequest = {
  normalizedKey: string;
  label: string;
  categoryId: string;
  etag: string;
  included: { transactionId: string; version: number }[];
  excludedIds: string[];
  remember: boolean;
};

type PickerState = {
  key: string;
  query: string;
  index: number;
  parentId: string | null;
};

export function MerchantGroupList({
  groups,
  categories,
  undo,
  saving,
  onApply,
  onUndo,
  onPaperPrimary,
}: {
  groups: MerchantGroupView[];
  categories: Category[];
  undo: MerchantUndo | null;
  saving: boolean;
  onApply: (request: MerchantApplyRequest) => void;
  onUndo: () => void;
  onPaperPrimary?: (active: boolean) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [excluded, setExcluded] = useState<Record<string, string[]>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [remember, setRemember] = useState<Record<string, boolean>>({});
  const [paperKey, setPaperKey] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerState | null>(null);
  const phone = usePhone();
  const searchRef = useRef<HTMLInputElement>(null);
  const paper = groups.some((group) => {
    const categoryId = drafts[group.normalizedKey] ?? "";
    const included = includedMembers(
      group,
      excluded[group.normalizedKey] ?? [],
    );
    return categoryId !== "" && included.length > 0;
  });

  useEffect(() => {
    onPaperPrimary?.(paper);
  }, [onPaperPrimary, paper]);

  useEffect(() => {
    if (picker === null) {
      return;
    }
    const field = searchRef.current;
    if (field === null) {
      return;
    }
    field.focus();
    const end = field.value.length;
    field.setSelectionRange(end, end);
  }, [picker]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) {
        return;
      }
      const target = event.target;
      if (isTyping(target) || groups.length === 0 || inDecision(target)) {
        return;
      }
      const key = focusKey ?? groups[0]?.normalizedKey ?? null;
      if (key === null) {
        return;
      }
      if (event.key === "p" || event.key === "P") {
        event.preventDefault();
        event.stopPropagation();
        setPicker({ key, query: "", index: 0, parentId: null });
        return;
      }
      if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        event.stopPropagation();
        const group = groups.find((item) => item.normalizedKey === key);
        if (group === undefined) {
          return;
        }
        setRemember((current) => ({
          ...current,
          [key]: !(
            current[key] ?? remembersByDefault(group.suggestionConfidence)
          ),
        }));
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
    };
  }, [focusKey, groups]);

  if (groups.length === 0 && undo === null) {
    return null;
  }

  const dockGroup =
    groups.find((group) => group.normalizedKey === paperKey) ??
    groups[0] ??
    null;

  return (
    <>
      {undo === null ? null : (
        <div className="toast" role="status">
          Categorized {undo.count}
          {undo.remember ? " · Rule saved" : ""}
          {" · "}
          <button
            className="toast-undo"
            type="button"
            onClick={onUndo}
            disabled={saving}
          >
            Undo
          </button>
        </div>
      )}
      {groups.length === 0 ? null : (
        <section className="merchant-groups" aria-label="Merchant groups">
          {groups.map((group) => {
            const excludedIds = excluded[group.normalizedKey] ?? [];
            const included = includedMembers(group, excludedIds);
            const categoryId = drafts[group.normalizedKey] ?? "";
            const category = categories.find((item) => item.id === categoryId);
            const open = expanded === group.normalizedKey;
            const future =
              remember[group.normalizedKey] ??
              remembersByDefault(group.suggestionConfidence);
            const ready = categoryId !== "" && included.length > 0 && !saving;
            const variant = !ready
              ? "ghost"
              : paperKey === group.normalizedKey
                ? "primary"
                : "outline";
            const label = applyLabel(included.length, group.members.length);
            const total = groupTotal(group.members);
            const dates = groupDates(group.members);
            return (
              <article
                key={group.normalizedKey}
                className="card merchant-group"
                onFocus={() => {
                  setFocusKey(group.normalizedKey);
                }}
              >
                <div className="merchant-group-head">
                  <button
                    className="merchant-expand"
                    type="button"
                    aria-expanded={open}
                    aria-label={
                      open
                        ? `Hide ${group.label} charges`
                        : `Show ${group.label} charges`
                    }
                    onClick={() => {
                      setExpanded(open ? null : group.normalizedKey);
                    }}
                  >
                    {open ? "▾" : "▸"}
                  </button>
                  <div className="merchant-group-title">
                    <h2>{group.label}</h2>
                    <p className="muted">
                      {group.members.length} pending
                      {dates === "" ? null : (
                        <span className="merchant-dates">{dates}</span>
                      )}
                    </p>
                  </div>
                  {total === null ? null : (
                    <p className="amount merchant-group-total">
                      <MoneyText text={total} />
                    </p>
                  )}
                </div>
                <div className="merchant-group-actions">
                  <MerchantCategoryField
                    group={group}
                    categories={categories}
                    categoryId={categoryId}
                    picker={picker?.key === group.normalizedKey ? picker : null}
                    searchRef={searchRef}
                    onOpen={() => {
                      setFocusKey(group.normalizedKey);
                      setPicker({
                        key: group.normalizedKey,
                        query: "",
                        index: 0,
                        parentId: null,
                      });
                    }}
                    onQuery={(query) => {
                      setPicker((current) =>
                        current === null
                          ? current
                          : { ...current, query, index: 0 },
                      );
                    }}
                    onHighlight={(index) => {
                      setPicker((current) =>
                        current === null ? current : { ...current, index },
                      );
                    }}
                    onDrill={(parentId) => {
                      setPicker((current) =>
                        current === null
                          ? current
                          : { ...current, parentId, query: "", index: 0 },
                      );
                    }}
                    onChoose={(nextId) => {
                      setDrafts((current) => ({
                        ...current,
                        [group.normalizedKey]: nextId,
                      }));
                      setPaperKey(group.normalizedKey);
                      setPicker(null);
                    }}
                    onClose={() => {
                      setPicker(null);
                    }}
                  />
                  <label className="merchant-future">
                    <input
                      type="checkbox"
                      role="switch"
                      checked={future}
                      onChange={() => {
                        setRemember((current) => ({
                          ...current,
                          [group.normalizedKey]: !future,
                        }));
                      }}
                    />
                    <span>
                      Always categorize {group.label}
                      {category === undefined ? "" : ` as ${category.name}`}
                    </span>
                  </label>
                  {phone ? null : (
                    <Button
                      className="merchant-apply"
                      variant={variant}
                      disabled={!ready}
                      onClick={() => {
                        submit(group);
                      }}
                    >
                      {label}
                    </Button>
                  )}
                </div>
                {open ? (
                  <ul className="merchant-members">
                    {group.members.map((member) => {
                      const checked = !excludedIds.includes(
                        member.transactionId,
                      );
                      return (
                        <li key={member.transactionId}>
                          <label>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                setExcluded((current) => {
                                  const prior = new Set(
                                    current[group.normalizedKey] ?? [],
                                  );
                                  if (prior.has(member.transactionId)) {
                                    prior.delete(member.transactionId);
                                  } else {
                                    prior.add(member.transactionId);
                                  }
                                  return {
                                    ...current,
                                    [group.normalizedKey]: [...prior],
                                  };
                                });
                              }}
                            />
                            <span>{member.counterparty}</span>
                            <span className="amount">
                              {member.amount === "" ? null : (
                                <MoneyText
                                  text={formatUnsigned({
                                    amount: member.amount,
                                    currency: member.currency || "SGD",
                                  })}
                                />
                              )}
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </article>
            );
          })}
          {phone && dockGroup !== null ? (
            <div className="merchant-save-dock">
              <Button
                className="merchant-apply"
                variant={
                  (drafts[dockGroup.normalizedKey] ?? "") !== "" &&
                  includedMembers(
                    dockGroup,
                    excluded[dockGroup.normalizedKey] ?? [],
                  ).length > 0 &&
                  !saving
                    ? "primary"
                    : "ghost"
                }
                disabled={
                  saving ||
                  (drafts[dockGroup.normalizedKey] ?? "") === "" ||
                  includedMembers(
                    dockGroup,
                    excluded[dockGroup.normalizedKey] ?? [],
                  ).length === 0
                }
                onClick={() => {
                  submit(dockGroup);
                }}
              >
                {applyLabel(
                  includedMembers(
                    dockGroup,
                    excluded[dockGroup.normalizedKey] ?? [],
                  ).length,
                  dockGroup.members.length,
                )}
              </Button>
            </div>
          ) : null}
        </section>
      )}
    </>
  );

  function submit(group: MerchantGroupView) {
    const categoryId = drafts[group.normalizedKey] ?? "";
    const excludedIds = excluded[group.normalizedKey] ?? [];
    const included = includedMembers(group, excludedIds);
    if (categoryId === "" || included.length === 0) {
      return;
    }
    onApply({
      normalizedKey: group.normalizedKey,
      label: group.label,
      categoryId,
      etag: group.etag,
      included: included.map((member) => ({
        transactionId: member.transactionId,
        version: member.version,
      })),
      excludedIds,
      remember:
        remember[group.normalizedKey] ??
        remembersByDefault(group.suggestionConfidence),
    });
  }
}

function MerchantCategoryField({
  group,
  categories,
  categoryId,
  picker,
  searchRef,
  onOpen,
  onQuery,
  onHighlight,
  onDrill,
  onChoose,
  onClose,
}: {
  group: MerchantGroupView;
  categories: Category[];
  categoryId: string;
  picker: PickerState | null;
  searchRef: RefObject<HTMLInputElement | null>;
  onOpen: () => void;
  onQuery: (query: string) => void;
  onHighlight: (index: number) => void;
  onDrill: (parentId: string | null) => void;
  onChoose: (categoryId: string) => void;
  onClose: () => void;
}) {
  const listId = useId();
  const open = picker !== null;
  const rows = merchantPickerRows(
    categories,
    picker?.query ?? "",
    picker?.parentId ?? null,
  );
  const active = rows[picker?.index ?? 0] ?? null;
  const draft =
    categories.find((category) => category.id === categoryId) ?? null;
  const parent =
    draft?.parent_id == null
      ? null
      : (categories.find((category) => category.id === draft.parent_id) ??
        null);
  return (
    <div className={`cat-picker merchant-category${open ? " is-open" : ""}`}>
      <span className="sr-only" id={`${listId}-label`}>
        Category for {group.label}
      </span>
      {open ? (
        <input
          ref={searchRef}
          className="field cat-picker-search"
          role="combobox"
          type="text"
          aria-expanded="true"
          aria-controls={listId}
          aria-labelledby={`${listId}-label`}
          placeholder="Search categories"
          value={picker?.query ?? ""}
          onChange={(event) => {
            onQuery(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onClose();
              return;
            }
            if (event.key === "ArrowDown") {
              event.preventDefault();
              onHighlight(Math.min(rows.length - 1, (picker?.index ?? 0) + 1));
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              onHighlight(Math.max(0, (picker?.index ?? 0) - 1));
              return;
            }
            if (event.key === "ArrowLeft" && (picker?.query ?? "") === "") {
              event.preventDefault();
              onDrill(null);
              return;
            }
            if (event.key === "Enter" && active !== null) {
              event.preventDefault();
              activate(active);
            }
          }}
        />
      ) : (
        <button
          className="select cat-picker-trigger"
          type="button"
          aria-expanded="false"
          aria-controls={listId}
          aria-labelledby={`${listId}-label`}
          onClick={onOpen}
        >
          {draft === null
            ? "Choose Category"
            : parent === null
              ? draft.name
              : `${parent.name} › ${draft.name}`}
        </button>
      )}
      {open ? (
        rows.length === 0 ? (
          <p className="cat-picker-empty">No matching Category</p>
        ) : (
          <ul className="cat-picker-list" id={listId} role="listbox">
            {rows.map((row, index) => (
              <li key={row.key}>
                <button
                  className={`cat-picker-option${index === (picker?.index ?? 0) ? " is-active" : ""}${row.kind === "just" ? " is-just" : ""}`}
                  type="button"
                  role="option"
                  aria-selected={index === (picker?.index ?? 0)}
                  onMouseEnter={() => {
                    onHighlight(index);
                  }}
                  onClick={() => {
                    activate(row);
                  }}
                >
                  {row.name}
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
  );

  function activate(row: (typeof rows)[number]) {
    if (row.kind === "back") {
      onDrill(null);
      return;
    }
    if (row.hasChildren) {
      onDrill(row.key);
      return;
    }
    if (row.categoryId !== null) {
      onChoose(row.categoryId);
    }
  }
}

function includedMembers(
  group: MerchantGroupView,
  excludedIds: string[],
): MerchantGroupMember[] {
  const excluded = new Set(excludedIds);
  return group.members.filter((member) => !excluded.has(member.transactionId));
}

function applyLabel(included: number, total: number): string {
  if (included === total) {
    return `Apply to all ${included}`;
  }
  return `Apply to ${included}`;
}

function groupTotal(members: MerchantGroupMember[]): string | null {
  const currency = members.find((member) => member.currency !== "")?.currency;
  if (currency === undefined) {
    return null;
  }
  const cents = members
    .filter((member) => member.currency === currency && member.amount !== "")
    .reduce((sum, member) => sum + Math.abs(amountToCents(member.amount)), 0);
  if (cents === 0) {
    return null;
  }
  return formatUnsigned(centsToMoney(cents, currency));
}

function groupDates(members: MerchantGroupMember[]): string {
  const dates = members
    .map((member) => member.effectiveDate)
    .filter((date) => date !== "")
    .sort();
  const first = dates[0];
  const last = dates[dates.length - 1];
  if (first === undefined || last === undefined) {
    return "";
  }
  const start = dayMonthLabel(first);
  const end = dayMonthLabel(last);
  return start === end ? start : `${start} – ${end}`;
}

function inDecision(target: EventTarget | null): boolean {
  return (
    target instanceof Element && target.closest("#review-decision") !== null
  );
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function usePhone(): boolean {
  const query = "(max-width: 52rem)";
  const [phone, setPhone] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(query).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(query);
    function onChange() {
      setPhone(media.matches);
    }
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, []);
  return phone;
}
