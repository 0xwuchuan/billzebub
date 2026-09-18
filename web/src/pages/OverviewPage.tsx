import type { Transaction } from "../api";
import {
  DitherBarChart,
  DitherDonutChart,
  type DitherSeries,
} from "../components/dither-kit/DitherCharts";
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
  weekComparison,
} from "../lib/workspace";

const CONFIRMATION_SERIES: DitherSeries[] = [
  {
    key: "confirmed",
    label: "Confirmed",
    color: "#879a39",
    variant: "gradient",
  },
  {
    key: "provisional",
    label: "Provisional",
    color: "#d0a215",
    variant: "dotted",
  },
];

const DITHER_CATEGORY_COLORS = [
  "#3aa99f",
  "#d0a215",
  "#879a39",
  "#8b7ec8",
  "#d14d41",
  "#878580",
];

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
  const week = weekComparison(transactions, today).map((day) => ({
    label: day.label,
    confirmed: day.confirmedCents,
    provisional: day.provisionalCents,
  }));
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
          <DitherBarChart
            data={week}
            series={CONFIRMATION_SERIES}
            height={92}
            ariaLabel="This week's spending stacked by confirmed and provisional transactions"
            valueFormatter={(cents) =>
              formatUnsigned(centsToMoney(cents, totals.currency))
            }
            stacked
          />
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
          <DitherDonutChart
            data={categories.map((category, index) => ({
              label: category.name,
              value: category.cents,
              color:
                DITHER_CATEGORY_COLORS[index % DITHER_CATEGORY_COLORS.length] ??
                "#878580",
            }))}
            ariaLabel="Confirmed spending by category"
          />
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
