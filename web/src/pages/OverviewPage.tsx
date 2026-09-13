import type { Transaction } from "../api";
import { TransactionRow } from "../components/TransactionRow";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { categoryColor, monthYearLabel } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import {
  categoryTotals,
  monthTotals,
  reportingPeriod,
  sortTransactions,
  weekBars,
} from "../lib/workspace";

export function OverviewPage({
  transactions,
  reviewCount,
  blockingCount,
  today,
  onOpenTransaction,
  onFilterConfirmed,
  onFilterProvisional,
  onOpenReview,
  onOpenTransactions,
  onFilterCategory,
}: {
  transactions: Transaction[];
  reviewCount: number;
  blockingCount: number;
  today: Date;
  onOpenTransaction: (id: string) => void;
  onFilterConfirmed: () => void;
  onFilterProvisional: () => void;
  onOpenReview: () => void;
  onOpenTransactions: () => void;
  onFilterCategory: (name: string) => void;
}) {
  const fresh = useEntrance("overview");
  const period = reportingPeriod(transactions, today);
  const totals = monthTotals(transactions, period);
  const categories = categoryTotals(transactions, period);
  const bars = weekBars(transactions, today);
  const recent = sortTransactions(transactions).slice(0, 6);
  const attention = Math.max(0, reviewCount - blockingCount);
  const failed = blockingCount > 0;
  return (
    <>
      <section className={`card statement${fresh ? " stage-enter" : ""}`}>
        <div className="statement-cell">
          <p className="eyebrow">
            {monthYearLabel(`${period}-01`)} · {totals.currency}
          </p>
          <p className="hero-value amount">
            {formatUnsigned(
              centsToMoney(totals.estimatedCents, totals.currency),
            )}
          </p>
          <p className="hero-sub">
            Estimated spending. Confirmed uses Posted Amount. Provisional uses
            eligible Real-time Claims.
          </p>
          <div className={`bars${fresh ? " is-fresh" : ""}`} aria-hidden="true">
            {bars.map((bar, index) => (
              <i
                key={bar.label}
                style={{
                  height: `${bar.pct}%`,
                  animationDelay: `${index * 10}ms`,
                }}
              />
            ))}
          </div>
          <div className="bar-labels">
            {bars.map((bar) => (
              <span key={bar.label}>{bar.label}</span>
            ))}
          </div>
        </div>
        <button
          className="statement-cell"
          type="button"
          data-action="filter-state"
          onClick={onFilterConfirmed}
        >
          <span className="cell-label">
            <i className="cell-dot confirmed" />
            Confirmed
          </span>
          <span className="cell-value amount">
            {formatUnsigned(
              centsToMoney(totals.confirmedCents, totals.currency),
            )}
          </span>
          <span className="cell-foot">
            <strong>{totals.confirmedCount}</strong> Transactions with a Posted
            Amount
          </span>
        </button>
        <button
          className="statement-cell tone-yellow"
          type="button"
          onClick={onFilterProvisional}
        >
          <span className="cell-label">
            <i className="cell-dot provisional" />
            Provisional
          </span>
          <span className="cell-value amount">
            {formatUnsigned(
              centsToMoney(totals.provisionalCents, totals.currency),
            )}
          </span>
          <span className="cell-foot">
            <strong>{totals.provisionalCount}</strong> awaiting a Statement
            Claim
          </span>
        </button>
        <button
          className={`statement-cell${failed ? " tone-red" : ""}`}
          type="button"
          onClick={onOpenReview}
        >
          <span className="cell-label">
            <i className={`cell-dot ${failed ? "blocking" : "review"}`} />
            Pending Review
          </span>
          <span className="cell-value amount">{reviewCount}</span>
          <span className="cell-foot">
            {reviewCount === 0
              ? "Queue is clear"
              : `${blockingCount} blocking Extraction · ${attention} attention`}
          </span>
        </button>
      </section>
      <article className="card split">
        <div className="ring-wrap">
          <CategoryRing parts={categories} />
          <p className="muted">Confirmed by Category</p>
        </div>
        <div className="cat-list">
          {categories.length === 0 ? (
            <p className="empty">No confirmed Expenses in this month yet.</p>
          ) : (
            categories.map((category) => (
              <button
                className="cat-row"
                type="button"
                key={category.name}
                onClick={() => {
                  onFilterCategory(category.name);
                }}
              >
                <span>
                  <i
                    className="swatch"
                    style={{ background: categoryColor(category.name) }}
                  />
                  {category.name}
                </span>
                <span className="amount">
                  {formatUnsigned(
                    centsToMoney(category.cents, totals.currency),
                  )}
                </span>
              </button>
            ))
          )}
        </div>
      </article>
      <section className="card recent">
        <div className="recent-head">
          <h2>Recent activity</h2>
          <Button variant="ghost" onClick={onOpenTransactions}>
            All Transactions
          </Button>
        </div>
        {recent.length === 0 ? (
          <p className="empty">
            No trusted Transactions yet. Process an accepted statement to begin.
          </p>
        ) : (
          recent.map((transaction) => (
            <TransactionRow
              key={transaction.id}
              transaction={transaction}
              compact
              onOpen={onOpenTransaction}
            />
          ))
        )}
      </section>
    </>
  );
}

function CategoryRing({
  parts,
}: {
  parts: Array<{ name: string; cents: number }>;
}) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const segments = ringSegments(parts, circumference);
  return (
    <svg viewBox="0 0 96 96" aria-hidden="true">
      <circle
        cx="48"
        cy="48"
        r={radius}
        fill="none"
        stroke="#282726"
        strokeWidth="10"
      />
      {segments.map((segment) => (
        <circle
          key={segment.name}
          cx="48"
          cy="48"
          r={radius}
          fill="none"
          stroke={categoryColor(segment.name)}
          strokeWidth="10"
          strokeDasharray={`${segment.length} ${circumference - segment.length}`}
          strokeDashoffset={segment.offset}
          transform="rotate(-90 48 48)"
        />
      ))}
    </svg>
  );
}

function ringSegments(
  parts: Array<{ name: string; cents: number }>,
  circumference: number,
): Array<{ name: string; length: number; offset: number }> {
  const total = parts.reduce((sum, part) => sum + part.cents, 0) || 1;
  const segments: Array<{ name: string; length: number; offset: number }> = [];
  let offset = 0;
  for (const part of parts) {
    const length = (part.cents / total) * circumference;
    segments.push({ name: part.name, length, offset });
    offset -= length;
  }
  return segments;
}
