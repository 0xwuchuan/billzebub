import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type {
  Category,
  RecurringCadence,
  RecurringCreateInput,
  RecurringPatch,
  RecurringSeries,
} from "../api";
import { CloseIcon, PlusIcon } from "../components/icons";
import { Button } from "../components/ui/Button";
import { CategoryChip } from "../components/ui/CategoryChip";
import { useEntrance } from "../hooks/useEntrance";
import { isoDate } from "../lib/labels";
import {
  cadenceLabel,
  categoryName,
  confidenceLabel,
  dueGroups,
  recurringAmountLabel,
  relativeDueLabel,
} from "../lib/recurrings";
import type { RecurringTab } from "../lib/route";

type AccountOption = {
  id: string;
  name: string;
  currency: string;
};

type EditorState =
  | { kind: "add" }
  | { kind: "confirm"; series: RecurringSeries }
  | { kind: "edit"; series: RecurringSeries }
  | { kind: "end"; series: RecurringSeries };

export function RecurringsPage({
  proposed,
  active,
  paused,
  categories,
  accounts,
  tab,
  loading,
  saving,
  error,
  today,
  onTab,
  onConfirm,
  onDismiss,
  onUpdate,
  onCreate,
  onNotice,
}: {
  proposed: RecurringSeries[];
  active: RecurringSeries[];
  paused: RecurringSeries[];
  categories: Category[];
  accounts: AccountOption[];
  tab: RecurringTab;
  loading: boolean;
  saving: string | null;
  error: string | null;
  today: Date;
  onTab: (tab: Exclude<RecurringTab, "">) => void;
  onConfirm: (seriesId: string, patch: RecurringPatch) => Promise<boolean>;
  onDismiss: (seriesId: string) => Promise<boolean>;
  onUpdate: (seriesId: string, patch: RecurringPatch) => Promise<boolean>;
  onCreate: (input: RecurringCreateInput) => Promise<boolean>;
  onNotice: (message: string) => void;
}) {
  const fresh = useEntrance("recurrings");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const explicit = tab === "proposed" || tab === "active" ? tab : null;
  const view =
    explicit ?? (loading ? null : proposed.length > 0 ? "proposed" : "active");
  const sheetHasPrimary = editor !== null && editor.kind !== "end";

  useEffect(() => {
    if (menuId === null) {
      return;
    }
    function onPointer(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      if (target.closest("[data-row-menu]") === null) {
        setMenuId(null);
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuId(null);
      }
    }
    document.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuId]);

  function focusRow(current: HTMLElement, delta: number) {
    const rows = [
      ...(listRef.current?.querySelectorAll<HTMLElement>(
        "[data-recurring-row]",
      ) ?? []),
    ];
    const index = rows.indexOf(current);
    const next = rows[index + delta];
    next?.focus();
  }

  function onListKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (isTextEntry(event.target) || editor !== null) {
      return;
    }
    const row =
      event.target instanceof HTMLElement
        ? event.target.closest<HTMLElement>("[data-recurring-row]")
        : null;
    if (row === null) {
      return;
    }
    if (event.key === "ArrowDown" || event.key === "j") {
      event.preventDefault();
      focusRow(row, 1);
      return;
    }
    if (event.key === "ArrowUp" || event.key === "k") {
      event.preventDefault();
      focusRow(row, -1);
      return;
    }
    if (event.key === "Enter" && event.target === row && view === "proposed") {
      const series = proposed.find((item) => item.id === row.dataset.seriesId);
      if (series === undefined) {
        return;
      }
      event.preventDefault();
      void activate(series);
    }
  }

  async function activate(series: RecurringSeries) {
    const ok = await onConfirm(series.id, { status: "active" });
    if (ok) {
      onNotice(`Confirmed ${series.counterparty}`);
    }
  }

  async function dismiss(series: RecurringSeries) {
    const ok = await onDismiss(series.id);
    if (ok) {
      onNotice(`Dismissed ${series.counterparty}`);
    }
  }

  return (
    <div className={`recurring-page${fresh ? " stage-enter" : ""}`}>
      <div className="recurring-toolbar">
        <div className="filters" aria-label="Recurrings">
          <button
            className="chip chip-quiet"
            type="button"
            aria-pressed={view === "proposed"}
            onClick={() => {
              onTab("proposed");
            }}
          >
            Proposed
          </button>
          <button
            className="chip chip-quiet"
            type="button"
            aria-pressed={view === "active"}
            onClick={() => {
              onTab("active");
            }}
          >
            Active
          </button>
        </div>
        <Button
          variant={sheetHasPrimary ? "ghost" : "primary"}
          onClick={() => {
            setEditor({ kind: "add" });
          }}
        >
          <PlusIcon />
          Add
        </Button>
      </div>
      {error !== null ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}
      {loading && view === null ? (
        <p className="empty">Loading recurrings…</p>
      ) : null}
      {view === "proposed" ? (
        <div
          className="recurring-list"
          ref={listRef}
          role="list"
          aria-label="Proposed recurrings"
          onKeyDown={onListKeyDown}
        >
          {proposed.length === 0 ? (
            <p className="empty">
              No proposals waiting.{" "}
              <button
                className="text-link"
                type="button"
                onClick={() => {
                  onTab("active");
                }}
              >
                Active
              </button>
              {" · "}
              <button
                className="text-link"
                type="button"
                onClick={() => {
                  setEditor({ kind: "add" });
                }}
              >
                Add
              </button>
            </p>
          ) : (
            proposed.map((series) => (
              <ProposedRow
                key={series.id}
                series={series}
                category={categoryName(categories, series.category_id)}
                selected={selectedId === series.id}
                saving={saving === series.id}
                onSelect={setSelectedId}
                onConfirm={() => {
                  setEditor({ kind: "confirm", series });
                }}
                onDismiss={() => {
                  void dismiss(series);
                }}
              />
            ))
          )}
        </div>
      ) : null}
      {view === "active" ? (
        <div
          className="recurring-list"
          ref={listRef}
          role="list"
          aria-label="Active recurrings"
          onKeyDown={onListKeyDown}
        >
          {active.length === 0 ? (
            <p className="empty">
              No active series yet. Add one, or wait for detections.
            </p>
          ) : (
            dueGroups(active, today).map((group) => (
              <section key={group.label} className="recurring-group">
                <h2 className="recurring-group-label">{group.label}</h2>
                {group.items.map((series) => (
                  <ActiveRow
                    key={series.id}
                    series={series}
                    category={categoryName(categories, series.category_id)}
                    account={accountName(accounts, series.primary_account_id)}
                    today={today}
                    menuOpen={menuId === series.id}
                    saving={saving === series.id}
                    onToggleMenu={() => {
                      setMenuId((current) =>
                        current === series.id ? null : series.id,
                      );
                    }}
                    onEdit={() => {
                      setMenuId(null);
                      setEditor({ kind: "edit", series });
                    }}
                    onPause={() => {
                      setMenuId(null);
                      void onUpdate(series.id, { status: "paused" }).then(
                        (ok) => {
                          if (ok) {
                            onNotice(`Paused ${series.counterparty}`);
                          }
                        },
                      );
                    }}
                    onEnd={() => {
                      setMenuId(null);
                      setEditor({ kind: "end", series });
                    }}
                  />
                ))}
              </section>
            ))
          )}
          {paused.length > 0 ? (
            <details className="paused-fold">
              <summary>{paused.length} paused</summary>
              <div className="recurring-list">
                {paused.map((series) => (
                  <ActiveRow
                    key={series.id}
                    series={series}
                    category={categoryName(categories, series.category_id)}
                    account={accountName(accounts, series.primary_account_id)}
                    today={today}
                    menuOpen={menuId === series.id}
                    saving={saving === series.id}
                    paused
                    onToggleMenu={() => {
                      setMenuId((current) =>
                        current === series.id ? null : series.id,
                      );
                    }}
                    onEdit={() => {
                      setMenuId(null);
                      setEditor({ kind: "edit", series });
                    }}
                    onResume={() => {
                      setMenuId(null);
                      void onUpdate(series.id, { status: "active" }).then(
                        (ok) => {
                          if (ok) {
                            onNotice(`Resumed ${series.counterparty}`);
                          }
                        },
                      );
                    }}
                    onEnd={() => {
                      setMenuId(null);
                      setEditor({ kind: "end", series });
                    }}
                  />
                ))}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
      {editor !== null ? (
        <SeriesDialog
          key={
            editor.kind === "add" ? "add" : `${editor.kind}:${editor.series.id}`
          }
          editor={editor}
          categories={categories}
          accounts={accounts}
          today={today}
          saving={saving !== null}
          onClose={() => {
            setEditor(null);
          }}
          onConfirm={async (series, patch) => {
            const ok = await onConfirm(series.id, patch);
            if (ok) {
              onNotice(`Confirmed ${series.counterparty}`);
              setEditor(null);
            }
          }}
          onUpdate={async (series, patch) => {
            const ok = await onUpdate(series.id, patch);
            if (ok) {
              onNotice(`Updated ${series.counterparty}`);
              setEditor(null);
            }
          }}
          onCreate={async (input) => {
            const ok = await onCreate(input);
            if (ok) {
              onNotice(`Added ${input.counterparty}`);
              setEditor(null);
              onTab("active");
            }
          }}
          onEnd={async (series) => {
            const ok = await onUpdate(series.id, { status: "ended" });
            if (ok) {
              onNotice(`Ended ${series.counterparty}`);
              setEditor(null);
            }
          }}
        />
      ) : null}
    </div>
  );
}

function ProposedRow({
  series,
  category,
  selected,
  saving,
  onSelect,
  onConfirm,
  onDismiss,
}: {
  series: RecurringSeries;
  category: string | null;
  selected: boolean;
  saving: boolean;
  onSelect: (id: string) => void;
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  const confidence = confidenceLabel(series.confidence);
  return (
    <article
      className="recurring-row is-proposed"
      role="listitem"
      tabIndex={0}
      data-recurring-row
      data-series-id={series.id}
      aria-current={selected ? "true" : undefined}
      onFocus={() => {
        onSelect(series.id);
      }}
    >
      <div className="recurring-row-top">
        <strong className="recurring-name">{series.counterparty}</strong>
        <span className="recurring-amount amount">
          {recurringAmountLabel(series.amount)}
        </span>
      </div>
      <div className="recurring-row-mid">
        <p className="recurring-meta">
          <span>{cadenceLabel(series.cadence, series.interval_days)}</span>
          {confidence !== null ? (
            <>
              <span aria-hidden="true"> · </span>
              <span className="recurring-confidence">{confidence}</span>
            </>
          ) : null}
        </p>
        <div className="recurring-actions">
          <Button variant="ghost" disabled={saving} onClick={onConfirm}>
            Confirm
          </Button>
          <Button
            variant="ghost"
            className="btn-quiet-danger"
            disabled={saving}
            onClick={onDismiss}
          >
            Dismiss
          </Button>
        </div>
      </div>
      {category !== null ? <CategoryChip name={category} /> : null}
    </article>
  );
}

function ActiveRow({
  series,
  category,
  account,
  today,
  menuOpen,
  saving,
  paused = false,
  onToggleMenu,
  onEdit,
  onPause,
  onResume,
  onEnd,
}: {
  series: RecurringSeries;
  category: string | null;
  account: string | null;
  today: Date;
  menuOpen: boolean;
  saving: boolean;
  paused?: boolean;
  onToggleMenu: () => void;
  onEdit: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onEnd: () => void;
}) {
  const menuId = useId();
  return (
    <article
      className="recurring-row is-active"
      role="listitem"
      tabIndex={0}
      data-recurring-row
      data-series-id={series.id}
    >
      <strong className="recurring-name">{series.counterparty}</strong>
      <p className="recurring-when recurring-meta">
        <span>{relativeDueLabel(series.next_expected_date, today)}</span>
        <span aria-hidden="true"> · </span>
        <span>{cadenceLabel(series.cadence, series.interval_days)}</span>
        {series.missed ? <span className="recurring-miss">Missed</span> : null}
      </p>
      <span className="recurring-amount amount">
        {recurringAmountLabel(series.amount)}
      </span>
      <div className="recurring-tax">
        {category !== null ? <CategoryChip name={category} /> : null}
      </div>
      <p className="recurring-account recurring-meta">{account ?? ""}</p>
      <div className="recurring-actions" data-row-menu>
        <button
          className="icon-btn"
          type="button"
          aria-label={`Actions for ${series.counterparty}`}
          aria-expanded={menuOpen}
          aria-controls={menuId}
          disabled={saving}
          onClick={onToggleMenu}
        >
          <span aria-hidden="true">⋯</span>
        </button>
        {menuOpen ? (
          <div className="row-menu-panel" id={menuId} role="menu">
            <button type="button" role="menuitem" onClick={onEdit}>
              Edit
            </button>
            {paused ? (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onResume?.();
                }}
              >
                Resume
              </button>
            ) : (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onPause?.();
                }}
              >
                Pause
              </button>
            )}
            <button type="button" role="menuitem" onClick={onEnd}>
              End
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function SeriesDialog({
  editor,
  categories,
  accounts,
  today,
  saving,
  onClose,
  onConfirm,
  onUpdate,
  onCreate,
  onEnd,
}: {
  editor: EditorState;
  categories: Category[];
  accounts: AccountOption[];
  today: Date;
  saving: boolean;
  onClose: () => void;
  onConfirm: (series: RecurringSeries, patch: RecurringPatch) => Promise<void>;
  onUpdate: (series: RecurringSeries, patch: RecurringPatch) => Promise<void>;
  onCreate: (input: RecurringCreateInput) => Promise<void>;
  onEnd: (series: RecurringSeries) => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const series = editor.kind === "add" ? null : editor.series;
  const [counterparty, setCounterparty] = useState(series?.counterparty ?? "");
  const [amount, setAmount] = useState(series?.amount.amount ?? "");
  const [currency, setCurrency] = useState(series?.amount.currency ?? "SGD");
  const [cadence, setCadence] = useState<RecurringCadence>(
    series?.cadence ?? "monthly",
  );
  const [intervalDays, setIntervalDays] = useState(
    series?.interval_days === null || series?.interval_days === undefined
      ? ""
      : String(series.interval_days),
  );
  const [nextExpected, setNextExpected] = useState(
    series?.next_expected_date ?? isoDate(today),
  );
  const [categoryId, setCategoryId] = useState(series?.category_id ?? "");
  const [accountId, setAccountId] = useState(series?.primary_account_id ?? "");
  const [formError, setFormError] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null || dialog.open) {
      return;
    }
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }, []);

  function close() {
    const dialog = dialogRef.current;
    if (dialog !== null && typeof dialog.close === "function") {
      dialog.close();
      return;
    }
    onClose();
  }

  function schedulePatch(): RecurringPatch | null {
    if (nextExpected === "") {
      setFormError("Next expected date is required.");
      return null;
    }
    const patch: RecurringPatch = {
      cadence,
      next_expected_date: nextExpected,
      category_id: categoryId === "" ? null : categoryId,
    };
    if (cadence === "custom_days") {
      const interval = Number(intervalDays);
      if (!Number.isInteger(interval) || interval < 1 || interval > 400) {
        setFormError(
          "Custom cadence needs an interval between 1 and 400 days.",
        );
        return null;
      }
      patch.interval_days = interval;
    }
    return patch;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (editor.kind === "end" && series !== null) {
      await onEnd(series);
      return;
    }
    if (editor.kind === "confirm" && series !== null) {
      const patch = schedulePatch();
      if (patch === null) {
        return;
      }
      await onConfirm(series, patch);
      return;
    }
    if (editor.kind === "edit" && series !== null) {
      const patch = schedulePatch();
      if (patch === null) {
        return;
      }
      const label = counterparty.trim();
      if (label === "") {
        setFormError("Counterparty is required.");
        return;
      }
      const cleaned = cleanAmount(amount);
      if (cleaned === null) {
        setFormError("Amount must be a positive number.");
        return;
      }
      await onUpdate(series, {
        ...patch,
        counterparty: label,
        amount: cleaned,
        currency,
        primary_account_id: accountId === "" ? null : accountId,
      });
      return;
    }
    const label = counterparty.trim();
    if (label === "") {
      setFormError("Counterparty is required.");
      return;
    }
    const cleaned = cleanAmount(amount);
    if (cleaned === null) {
      setFormError("Amount must be a positive number.");
      return;
    }
    if (nextExpected === "") {
      setFormError("Next expected date is required.");
      return;
    }
    const input: RecurringCreateInput = {
      counterparty: label,
      amount: cleaned,
      currency,
      cadence,
      next_expected_date: nextExpected,
    };
    if (cadence === "custom_days") {
      const interval = Number(intervalDays);
      if (!Number.isInteger(interval) || interval < 1 || interval > 400) {
        setFormError(
          "Custom cadence needs an interval between 1 and 400 days.",
        );
        return;
      }
      input.interval_days = interval;
    }
    if (categoryId !== "") {
      input.category_id = categoryId;
    }
    if (accountId !== "") {
      input.primary_account_id = accountId;
    }
    await onCreate(input);
  }

  const title =
    editor.kind === "add"
      ? "Add series"
      : editor.kind === "confirm"
        ? editor.series.counterparty
        : editor.kind === "end"
          ? `End ${editor.series.counterparty}?`
          : `Edit ${editor.series.counterparty}`;
  const eyebrow =
    editor.kind === "confirm"
      ? "Proposed"
      : editor.kind === "edit"
        ? editor.series.source === "manual"
          ? "Manual"
          : "Detected"
        : "Recurrings";

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog recurring-dialog"
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          close();
        }
      }}
    >
      <form onSubmit={(event) => void submit(event)}>
        <div className="settings-dialog-head">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h2 id={titleId}>{title}</h2>
            {editor.kind === "confirm" ? (
              <p className="amount recurring-dialog-amount">
                {recurringAmountLabel(editor.series.amount)}
              </p>
            ) : null}
          </div>
          <button className="icon-btn" type="button" onClick={close}>
            <CloseIcon />
            <span className="sr-only">Close</span>
          </button>
        </div>
        <div className="settings-dialog-body stack">
          {editor.kind === "end" ? (
            <p>Ends matching future txs.</p>
          ) : (
            <>
              {editor.kind === "add" || editor.kind === "edit" ? (
                <>
                  <label className="field-label">
                    Counterparty
                    <input
                      className="field"
                      value={counterparty}
                      onChange={(event) => {
                        setCounterparty(event.target.value);
                      }}
                    />
                  </label>
                  <label className="field-label">
                    Amount
                    <input
                      className="field"
                      inputMode="decimal"
                      value={amount}
                      onChange={(event) => {
                        setAmount(event.target.value);
                      }}
                    />
                  </label>
                  <label className="field-label">
                    Account
                    <select
                      className="select"
                      value={accountId}
                      onChange={(event) => {
                        const next = event.target.value;
                        setAccountId(next);
                        const account = accounts.find(
                          (item) => item.id === next,
                        );
                        if (account !== undefined && editor.kind === "add") {
                          setCurrency(account.currency);
                        }
                      }}
                    >
                      <option value="">No account</option>
                      {accounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : null}
              <label className="field-label">
                Cadence
                <select
                  className="select"
                  value={cadence}
                  onChange={(event) => {
                    setCadence(event.target.value as RecurringCadence);
                  }}
                >
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="yearly">Yearly</option>
                  <option value="custom_days">Custom days</option>
                </select>
              </label>
              {cadence === "custom_days" ? (
                <label className="field-label">
                  Interval days
                  <input
                    className="field"
                    inputMode="numeric"
                    value={intervalDays}
                    onChange={(event) => {
                      setIntervalDays(event.target.value);
                    }}
                  />
                </label>
              ) : null}
              <label className="field-label">
                Next expected
                <input
                  className="field"
                  type="date"
                  value={nextExpected}
                  onChange={(event) => {
                    setNextExpected(event.target.value);
                  }}
                />
              </label>
              <CategoryField
                categories={categories}
                value={categoryId}
                onChange={setCategoryId}
              />
            </>
          )}
          {formError !== "" ? (
            <p className="error-banner" role="alert">
              {formError}
            </p>
          ) : null}
          <div className="recurring-form-actions">
            <Button variant="ghost" onClick={close} disabled={saving}>
              Cancel
            </Button>
            <Button
              variant={editor.kind === "end" ? "danger" : "primary"}
              type="submit"
              disabled={saving}
            >
              {editor.kind === "add"
                ? "Add"
                : editor.kind === "end"
                  ? "End"
                  : editor.kind === "confirm"
                    ? "Confirm"
                    : "Save"}
            </Button>
          </div>
        </div>
      </form>
    </dialog>
  );
}

function CategoryField({
  categories,
  value,
  onChange,
}: {
  categories: Category[];
  value: string;
  onChange: (categoryId: string) => void;
}) {
  return (
    <fieldset className="cat-choice">
      <legend className="field-label">Category</legend>
      <div className="cat-choice-options">
        <button
          className="chip chip-quiet"
          type="button"
          aria-pressed={value === ""}
          onClick={() => {
            onChange("");
          }}
        >
          No category
        </button>
        {categories.map((category) => (
          <button
            className={`cat-choice-option${value === category.id ? " is-selected" : ""}`}
            type="button"
            aria-pressed={value === category.id}
            key={category.id}
            onClick={() => {
              onChange(category.id);
            }}
          >
            <CategoryChip name={category.name} />
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function accountName(
  accounts: AccountOption[],
  accountId: string | null,
): string | null {
  if (accountId === null) {
    return null;
  }
  return accounts.find((account) => account.id === accountId)?.name ?? null;
}

function cleanAmount(raw: string): string | null {
  const trimmed = raw.trim();
  if (!/^\d+(?:\.\d+)?$/.test(trimmed)) {
    return null;
  }
  if (Number(trimmed) <= 0) {
    return null;
  }
  return trimmed;
}

function isTextEntry(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  );
}
