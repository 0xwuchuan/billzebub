import type { StatementCoverageReport } from "../api";
import { shortMonthLabel } from "../lib/labels";

export function StatementCoveragePanel({
  coverage,
  selectedAccountId,
  onSelectAccount,
  onClearAccount,
}: {
  coverage: StatementCoverageReport | null;
  selectedAccountId: string | null;
  onSelectAccount: (accountId: string) => void;
  onClearAccount?: () => void;
}) {
  const accounts = coverage?.accounts ?? [];
  return (
    <section
      className="card settings-section coverage-panel"
      aria-label="Statement coverage"
    >
      <div className="panel-head coverage-head">
        <div>
          <h2>Statement coverage</h2>
          <p className="coverage-lede">
            Last {coverage?.window_months ?? 6} months ·{" "}
            {coverage?.timezone ?? "Asia/Singapore"}. Missing months have no
            accepted Extraction covering that calendar month.
          </p>
        </div>
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
      {accounts.length === 0 ? (
        <p className="coverage-empty">
          No statement-backed Financial Accounts yet.
        </p>
      ) : (
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
                  {account.display_name}
                </button>
                <div className="coverage-months">
                  {account.months.map((item) => {
                    const label = `${shortMonthLabel(item.month)} ${item.status}`;
                    const missing = item.status === "missing";
                    if (missing) {
                      return (
                        <button
                          className={`coverage-chip is-${item.status}`}
                          type="button"
                          key={item.month}
                          aria-label={`${account.display_name} ${label}`}
                          onClick={() => {
                            onSelectAccount(account.id);
                          }}
                        >
                          <span>{shortMonthLabel(item.month)}</span>
                          <span className="coverage-status">{item.status}</span>
                        </button>
                      );
                    }
                    return (
                      <span
                        className={`coverage-chip is-${item.status}`}
                        key={item.month}
                      >
                        <span className="sr-only">{account.display_name} </span>
                        <span>{shortMonthLabel(item.month)}</span>
                        <span className="coverage-status">{item.status}</span>
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
