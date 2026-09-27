import type { Transaction } from "../api";
import { CategoryRankList } from "../components/CategoryRankList";
import {
  DitherBarChart,
  DitherDonutChart,
} from "../components/dither-kit/DitherCharts";
import { TxRow } from "../components/TxRow";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { CONFIRMATION_SERIES } from "../lib/chartSeries";
import { categoryColor, categoryPrimary, monthYearLabel } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import {
  categoryTotals,
  monthTotals,
  reportingPeriod,
  sortTransactions,
  weekComparison,
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
  const week = weekComparison(transactions, today).map((day) => ({
    label: day.label,
    confirmed: day.confirmedCents,
    provisional: day.provisionalCents,
  }));
  const recent = sortTransactions(transactions).slice(0, 6);
  const attention = Math.max(0, reviewCount - blockingCount);
  const failed = blockingCount > 0;
  return (
    <div className={`dash-grid${fresh ? " stage-enter" : ""}`}>
      <section className="card dash-card">
        <div className="dash-card-body">
          <div>
            <p className="eyebrow">Monthly spending</p>
            <p className="hero-value amount">
              {formatUnsigned(
                centsToMoney(totals.estimatedCents, totals.currency),
              )}
            </p>
            <p className="hero-sub">
              {monthYearLabel(`${period}-01`)} · confirmed uses Posted Amount.
              Provisional uses eligible Real-time Claims.
            </p>
          </div>
          <div className="dash-week">
            <p className="dash-caption">This week</p>
            <DitherBarChart
              data={week}
              series={CONFIRMATION_SERIES}
              height={108}
              ariaLabel="This week's spending stacked by confirmed and provisional transactions"
              valueFormatter={(cents) =>
                formatUnsigned(centsToMoney(cents, totals.currency))
              }
              stacked
            />
          </div>
          <div className="dash-metrics">
            <button
              className="dash-metric"
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
                <strong>{totals.confirmedCount}</strong> Transactions with a
                Posted Amount
              </span>
            </button>
            <button
              className="dash-metric"
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
          </div>
        </div>
      </section>

      <section className="card dash-card dash-review">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Attention</p>
            <h2>Transactions to review</h2>
          </div>
          <Button variant="ghost" onClick={onOpenReview}>
            Review
          </Button>
        </div>
        <button
          className={`dash-metric dash-review-metric${failed ? " tone-red" : ""}`}
          type="button"
          onClick={onOpenReview}
        >
          <span className="cell-label">
            <i className={`cell-dot ${failed ? "blocking" : "review"}`} />
            Pending Review
          </span>
          <span className="dash-review-count amount">{reviewCount}</span>
          <span className="cell-foot">
            {reviewCount === 0
              ? "Queue is clear"
              : `${blockingCount} blocking Extraction · ${attention} attention`}
          </span>
        </button>
      </section>

      <article className="card dash-card dash-span">
        <div className="panel-head">
          <div>
            <p className="eyebrow">This month</p>
            <h2>Top categories</h2>
          </div>
        </div>
        <div className="split">
          <div className="ring-wrap">
            <DitherDonutChart
              data={categories.map((item) => ({
                label: item.name,
                value: item.cents,
                color: categoryColor(categoryPrimary(item.name)),
              }))}
              ariaLabel="Spending by category this month"
            />
            <p className="muted">Confirmed and categorized provisional</p>
          </div>
          <CategoryRankList
            categories={categories}
            currency={totals.currency}
            onSelect={onFilterCategory}
          />
        </div>
      </article>

      <section className="card dash-card dash-span recent">
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
            <TxRow
              key={transaction.id}
              transaction={transaction}
              provisionalMark="dot"
              onOpen={onOpenTransaction}
            />
          ))
        )}
      </section>
    </div>
  );
}
