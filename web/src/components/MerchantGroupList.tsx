import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

import type { Category } from "../api";
import { useOverlayMedia } from "../hooks/useOverlayMedia";
import {
  buildPickerRows,
  draftFromCategory,
  reducePickerKey,
  type PickerRow,
  type PickerState as TreePicker,
} from "../lib/categoryTree";
import { dayMonthLabel } from "../lib/labels";
import {
  remembersByDefault,
  type MerchantGroupMember,
  type MerchantGroupView,
} from "../lib/merchantGroups";
import { amountToCents, centsToMoney, formatUnsigned } from "../lib/money";
import { CategoryPicker } from "./CategoryPicker";
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
  const [skipped, setSkipped] = useState<string[]>([]);
  const phone = usePhone();
  const sheet = useOverlayMedia();
  const searchRef = useRef<HTMLInputElement>(null);
  const visibleGroups = useMemo(
    () => groups.filter((group) => !skipped.includes(group.normalizedKey)),
    [groups, skipped],
  );
  const paper = visibleGroups.some((group) => {
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
      if (undo !== null && !event.isComposing && isUndoKey(event)) {
        if (event.metaKey || event.ctrlKey || !isTyping(event.target)) {
          event.preventDefault();
          event.stopPropagation();
          onUndo();
          return;
        }
      }
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.isComposing ||
        (event.altKey && event.key !== "Enter")
      ) {
        return;
      }
      const target = event.target;
      const inMerchant =
        target instanceof Element &&
        target.closest(".merchant-category") !== null;
      if (
        !inMerchant &&
        (isTyping(target) || visibleGroups.length === 0 || inDecision(target))
      ) {
        return;
      }
      if (inMerchant && picker !== null) {
        const rows = merchantRows(categories, picker, drafts[picker.key] ?? "");
        const next = reducePickerKey(toTree(picker), rows, event.key, {
          alt: event.altKey,
        });
        const changed =
          next.effect !== null ||
          !next.state.open ||
          next.state.index !== picker.index ||
          next.state.parentId !== picker.parentId ||
          next.state.query !== picker.query;
        if (!changed) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        if (next.effect?.type === "assign") {
          const categoryId = next.effect.categoryId;
          const chosen = picker.key;
          setDrafts((current) => ({
            ...current,
            [chosen]: categoryId,
          }));
          setPaperKey(chosen);
          setPicker(null);
          return;
        }
        if (next.effect?.type === "close" || !next.state.open) {
          setPicker(null);
          return;
        }
        setPicker({
          key: picker.key,
          query: next.state.query,
          index: next.state.index,
          parentId: next.state.parentId,
        });
        return;
      }
      const key = focusKey ?? visibleGroups[0]?.normalizedKey ?? null;
      if (
        key === null ||
        !visibleGroups.some((group) => group.normalizedKey === key)
      ) {
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
        const group = visibleGroups.find((item) => item.normalizedKey === key);
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
  }, [categories, drafts, focusKey, onUndo, picker, undo, visibleGroups]);

  if (visibleGroups.length === 0 && undo === null) {
    return null;
  }

  const dockGroup =
    visibleGroups.find((group) => group.normalizedKey === paperKey) ??
    visibleGroups[0] ??
    null;

  return (
    <>
      {undo === null ? null : (
        <div className="toast merchant-undo-toast" role="status">
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
      {visibleGroups.length === 0 ? null : (
        <section className="merchant-groups" aria-label="Merchant groups">
          {visibleGroups.map((group) => {
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
                        <span className="merchant-dates">
                          {" · "}
                          {dates}
                        </span>
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
                    sheet={sheet}
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
                          : {
                              ...current,
                              query,
                              index: 0,
                              parentId:
                                query.trim() === "" ? current.parentId : null,
                            },
                      );
                    }}
                    onHighlight={(index) => {
                      setPicker((current) =>
                        current === null ? current : { ...current, index },
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
                    onMove={(next) => {
                      setPicker((current) =>
                        current === null || current.key !== group.normalizedKey
                          ? current
                          : { ...current, ...next },
                      );
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
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setSkipped((current) =>
                        current.includes(group.normalizedKey)
                          ? current
                          : [...current, group.normalizedKey],
                      );
                      setExpanded((current) =>
                        current === group.normalizedKey ? null : current,
                      );
                      setPicker((current) =>
                        current?.key === group.normalizedKey ? null : current,
                      );
                      setPaperKey((current) =>
                        current === group.normalizedKey ? null : current,
                      );
                    }}
                  >
                    Skip merchant
                  </Button>
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
  sheet,
  onOpen,
  onQuery,
  onHighlight,
  onChoose,
  onMove,
  onClose,
}: {
  group: MerchantGroupView;
  categories: Category[];
  categoryId: string;
  picker: PickerState | null;
  searchRef: RefObject<HTMLInputElement | null>;
  sheet: boolean;
  onOpen: () => void;
  onQuery: (query: string) => void;
  onHighlight: (index: number) => void;
  onChoose: (categoryId: string) => void;
  onMove: (next: {
    query: string;
    index: number;
    parentId: string | null;
  }) => void;
  onClose: () => void;
}) {
  const listId = useId();
  const labelId = `${listId}-label`;
  const open = picker !== null;
  const tree = toTree(picker);
  const rows = merchantRows(categories, picker, categoryId);
  return (
    <div className="merchant-category">
      <span className="sr-only" id={labelId}>
        Category for {group.label}
      </span>
      <CategoryPicker
        rows={rows}
        draft={draftFromCategory(categories, categoryId)}
        open={open}
        query={tree.query}
        activeIndex={tree.index}
        inputId={`${listId}-input`}
        listId={listId}
        searchRef={searchRef}
        sheet={sheet}
        labelledBy={labelId}
        onOpen={onOpen}
        onDismiss={onClose}
        onQuery={onQuery}
        onHighlight={onHighlight}
        onActivate={(row) => {
          const index = rows.findIndex((item) => item.key === row.key);
          const next = reducePickerKey(
            { ...tree, index: index < 0 ? tree.index : index },
            rows,
            "Enter",
          );
          if (next.effect?.type === "assign") {
            onChoose(next.effect.categoryId);
            return;
          }
          if (next.effect?.type === "close" || !next.state.open) {
            onClose();
            return;
          }
          onMove({
            query: next.state.query,
            index: next.state.index,
            parentId: next.state.parentId,
          });
        }}
      />
    </div>
  );
}

function merchantRows(
  categories: Category[],
  picker: PickerState | null,
  categoryId: string,
): PickerRow[] {
  return buildPickerRows({
    categories,
    query: picker?.query ?? "",
    parentId: picker?.parentId ?? null,
    placing: false,
    selectedId: categoryId === "" ? null : categoryId,
    recentIds: [],
    usage: new Map(),
    allowCreate: false,
  });
}

function toTree(picker: PickerState | null): TreePicker {
  return {
    open: picker !== null,
    query: picker?.query ?? "",
    index: picker?.index ?? 0,
    parentId: picker?.parentId ?? null,
    placing: false,
  };
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

function isUndoKey(event: KeyboardEvent): boolean {
  return !event.altKey && (event.key === "z" || event.key === "Z");
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
