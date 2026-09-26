import type { Transaction } from "../api";
import { CategoryRankList } from "../components/CategoryRankList";
import {
  DitherBarChart,
  DitherDonutChart,
} from "../components/dither-kit/DitherCharts";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { CONFIRMATION_SERIES } from "../lib/chartSeries";
import { categoryColor, categoryPrimary } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import {
  categoryTotals,
  monthTotals,
  monthlySpending,
  reportingPeriod,
} from "../lib/workspace";

export function SpendingPage({
  transactions,
  today,
  onOpenTransactions,
}: {
  transactions: Transaction[];
  today: Date;
  onOpenTransactions: () => void;
}) {
  const fresh = useEntrance("spending");
  const period = reportingPeriod(transactions, today);
  const month = monthTotals(transactions, period);
  const months = monthlySpending(transactions, today, 6);
  const categories = categoryTotals(transactions, period);
  const confirmedCents = months.reduce(
    (sum, item) => sum + item.confirmedCents,
    0,
  );
  const provisionalCents = months.reduce(
    (sum, item) => sum + item.provisionalCents,
    0,
  );
  const estimatedCents = confirmedCents + provisionalCents;
  const activeMonths = Math.max(
    1,
    months.filter((item) => item.estimatedCents > 0).length,
  );
  const categoryData = categories.slice(0, 8).map((item) => ({
    label: item.name,
    value: item.cents,
    color: categoryColor(categoryPrimary(item.name)),
  }));

  return (
    <div className={`spending-page${fresh ? " stage-enter" : ""}`}>
      <section className="card dash-card">
        <div className="dash-card-body spend-hero">
          <div className="spend-hero-copy">
            <p className="eyebrow">Spent this month</p>
            <p className="hero-value amount">
              {formatUnsigned(
                centsToMoney(month.estimatedCents, month.currency),
              )}
            </p>
            <p className="muted">
              Confirmed plus eligible provisional activity. Share bars are of
              this month's confirmed spend, not a budget.
            </p>
          </div>
          {categoryData.length === 0 ? null : (
            <DitherDonutChart
              data={categoryData}
              size={148}
              ariaLabel="This month's confirmed spending by category"
            />
          )}
        </div>
        <div className="spend-cats">
          <CategoryRankList categories={categories} currency={month.currency} />
        </div>
      </section>

      <section
        className="spending-stats"
        aria-label="Six month spending summary"
      >
        <article className="card metric-card">
          <p className="eyebrow">Six-month estimate</p>
          <p className="metric-value amount">
            {formatUnsigned(centsToMoney(estimatedCents, "SGD"))}
          </p>
          <p className="muted">Confirmed plus eligible provisional activity</p>
        </article>
        <article className="card metric-card">
          <p className="eyebrow">Confirmed</p>
          <p className="metric-value amount">
            {formatUnsigned(centsToMoney(confirmedCents, "SGD"))}
          </p>
          <p className="muted">Posted Amounts from accepted statements</p>
        </article>
        <article className="card metric-card">
          <p className="eyebrow">Active-month average</p>
          <p className="metric-value amount">
            {formatUnsigned(
              centsToMoney(Math.round(estimatedCents / activeMonths), "SGD"),
            )}
          </p>
          <p className="muted">Across months with recorded spending</p>
        </article>
      </section>

      <section className="card analytics-card">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Trend</p>
            <h2>Spending by month</h2>
          </div>
          <Button variant="ghost" onClick={onOpenTransactions}>
            View Transactions
          </Button>
        </div>
        <div className="analytics-chart">
          <DitherBarChart
            data={months.map((item) => ({
              label: item.label,
              confirmed: item.confirmedCents,
              provisional: item.provisionalCents,
            }))}
            series={CONFIRMATION_SERIES}
            height={220}
            ariaLabel="Confirmed and provisional spending across the last six months"
            valueFormatter={(cents) =>
              formatUnsigned(centsToMoney(cents, "SGD"))
            }
          />
        </div>
      </section>
    </div>
  );
}
