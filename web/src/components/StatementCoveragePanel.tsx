import { useId, useState } from "react";

import type { StatementCoverageReport } from "../api";
import { shortMonthLabel } from "../lib/labels";
import { UserLabel } from "./UserLabel";

const COVERAGE_EXPANDED_KEY = "bz.imports.coverageExpanded";

export function StatementCoveragePanel({
  coverage,
  selectedAccountId,
  onSelectAccount,
  onClearAccount,
  expanded,
  onExpandedChange,
  defaultCollapsed = true,
}: {
  coverage: StatementCoverageReport | null;
  selectedAccountId: string | null;
  onSelectAccount: (accountId: string) => void;
  onClearAccount?: () => void;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  defaultCollapsed?: boolean;
}) {
  const bodyId = useId();
  const controlled = expanded !== undefined;
  const [storedExpanded, setStoredExpanded] = useState(() =>
    readCoverageExpanded(defaultCollapsed),
  );
  const open = controlled ? expanded : storedExpanded;
  const accounts = coverage?.accounts ?? [];

  function setOpen(next: boolean) {
    writeCoverageExpanded(next);
    onExpandedChange?.(next);
    if (!controlled) {
      setStoredExpanded(next);
    }
  }

  return (
    <section
      className={`card settings-section coverage-panel${open ? " is-expanded" : " is-collapsed"}`}
      aria-label="Statement coverage"
    >
      <div className="panel-head coverage-head">
        <h2 className="coverage-heading">
          <button
            className="coverage-toggle"
            type="button"
            aria-expanded={open}
            aria-controls={open ? bodyId : undefined}
            onClick={() => {
              setOpen(!open);
            }}
          >
            <span className="coverage-chevron" aria-hidden="true">
              {open ? "▾" : "▸"}
            </span>
            <span className="coverage-title">Statement coverage</span>
            {open ? null : <CoverageSummary coverage={coverage} />}
          </button>
        </h2>
        {selectedAccountId !== null && onClearAccount !== undefined ? (
          <button
            className="chip chip-quiet"
            type="button"
            onClick={onClearAccount}
          >
            All accounts
          </button>
        ) : null}
      </div>
      {open ? (
        <div id={bodyId} className="coverage-body">
          <p className="coverage-lede">
            Last {coverage?.window_months ?? 6} months ·{" "}
            {coverage?.timezone ?? "Asia/Singapore"}. Missing months have no
            accepted Extraction covering that calendar month.
          </p>
          {accounts.length === 0 ? (
            <p className="coverage-empty">
              No statement-backed Financial Accounts yet.
            </p>
          ) : (
            <>
              <div className="coverage-list">
                {accounts.map((account) => {
                  const selected = selectedAccountId === account.id;
                  return (
                    <div
                      className={`coverage-row${selected ? " is-selected" : ""}`}
                      key={account.id}
                    >
                      <button
                        className="coverage-account"
                        type="button"
                        aria-pressed={selected}
                        onClick={() => {
                          onSelectAccount(account.id);
                        }}
                      >
                        <UserLabel
                          value={account.display_name}
                          kind="account"
                        />
                      </button>
                      <div className="coverage-months">
                        {account.months.map((item) => {
                          const label = `${account.display_name} · ${shortMonthLabel(item.month)} · ${item.status}`;
                          const month = shortMonthLabel(item.month);
                          if (item.status === "missing") {
                            return (
                              <button
                                className={`coverage-chip is-${item.status}`}
                                type="button"
                                key={item.month}
                                title={label}
                                aria-label={label}
                                onClick={() => {
                                  onSelectAccount(account.id);
                                }}
                              >
                                {month}
                              </button>
                            );
                          }
                          return (
                            <span
                              className={`coverage-chip is-${item.status}`}
                              key={item.month}
                              title={label}
                              aria-label={label}
                              role="img"
                            >
                              {month}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
              <ul className="coverage-legend" aria-label="Coverage status">
                <li>
                  <i
                    className="coverage-swatch is-present"
                    aria-hidden="true"
                  />
                  present
                </li>
                <li>
                  <i
                    className="coverage-swatch is-partial"
                    aria-hidden="true"
                  />
                  partial
                </li>
                <li>
                  <i
                    className="coverage-swatch is-missing"
                    aria-hidden="true"
                  />
                  missing
                </li>
              </ul>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

function CoverageSummary({
  coverage,
}: {
  coverage: StatementCoverageReport | null;
}) {
  const counts = countCoverage(coverage);
  const windowMonths = coverage?.window_months ?? 6;
  const timezone = coverage?.timezone ?? "Asia/Singapore";
  return (
    <span className="coverage-units">
      <CoverageCounts counts={counts} />
      <span className="coverage-unit">last {windowMonths} mo</span>
      <span className="coverage-unit">{timezone}</span>
    </span>
  );
}

function CoverageCounts({
  counts,
}: {
  counts: { accounts: number; missing: number; partial: number };
}) {
  if (counts.accounts === 0) {
    return <span className="coverage-unit">No accounts yet</span>;
  }
  if (counts.missing === 0 && counts.partial === 0) {
    return (
      <span className="coverage-unit coverage-count is-present">
        all present
      </span>
    );
  }
  return (
    <>
      {counts.missing > 0 ? (
        <span className="coverage-unit coverage-count is-missing">
          {counts.missing} missing
        </span>
      ) : null}
      {counts.partial > 0 ? (
        <span className="coverage-unit coverage-count is-partial">
          {counts.partial} partial
        </span>
      ) : null}
    </>
  );
}

function countCoverage(coverage: StatementCoverageReport | null): {
  accounts: number;
  missing: number;
  partial: number;
  present: number;
} {
  let missing = 0;
  let partial = 0;
  let present = 0;
  for (const account of coverage?.accounts ?? []) {
    for (const month of account.months) {
      if (month.status === "missing") {
        missing += 1;
      } else if (month.status === "partial") {
        partial += 1;
      } else {
        present += 1;
      }
    }
  }
  return {
    accounts: coverage?.accounts.length ?? 0,
    missing,
    partial,
    present,
  };
}

function readCoverageExpanded(defaultCollapsed: boolean): boolean {
  try {
    const stored = sessionStorage.getItem(COVERAGE_EXPANDED_KEY);
    if (stored === "true") {
      return true;
    }
    if (stored === "false") {
      return false;
    }
  } catch {
    return !defaultCollapsed;
  }
  return !defaultCollapsed;
}

function writeCoverageExpanded(expanded: boolean): void {
  try {
    sessionStorage.setItem(COVERAGE_EXPANDED_KEY, expanded ? "true" : "false");
  } catch {
    return;
  }
}
