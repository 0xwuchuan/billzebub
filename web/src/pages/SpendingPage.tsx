import type { Transaction } from "../api";
import {
  DitherBarChart,
  DitherDonutChart,
  type DitherSeries,
} from "../components/dither-kit/DitherCharts";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { centsToMoney, formatUnsigned } from "../lib/money";
import { categoryTotalsForMonths, monthlySpending } from "../lib/workspace";

const MONTH_SERIES: DitherSeries[] = [
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

const CATEGORY_COLORS = [
  "#3aa99f",
  "#d0a215",
  "#879a39",
  "#8b7ec8",
  "#d14d41",
  "#878580",
];

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
  const months = monthlySpending(transactions, today, 6);
  const categories = categoryTotalsForMonths(
    transactions,
    months.map((month) => month.month),
  );
  const confirmedCents = months.reduce(
    (sum, month) => sum + month.confirmedCents,
    0,
  );
  const provisionalCents = months.reduce(
    (sum, month) => sum + month.provisionalCents,
    0,
  );
  const estimatedCents = confirmedCents + provisionalCents;
  const activeMonths = Math.max(
    1,
    months.filter((month) => month.estimatedCents > 0).length,
  );
  const categoryData = categories.slice(0, 6).map((category, index) => ({
    label: category.name,
    value: category.cents,
    color: CATEGORY_COLORS[index % CATEGORY_COLORS.length] ?? "#878580",
  }));

  return (
    <div className={`spending-page${fresh ? " stage-enter" : ""}`}>
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
            data={months.map((month) => ({
              label: month.label,
              confirmed: month.confirmedCents,
              provisional: month.provisionalCents,
            }))}
            series={MONTH_SERIES}
            height={220}
            ariaLabel="Confirmed and provisional spending across the last six months"
            valueFormatter={(cents) =>
              formatUnsigned(centsToMoney(cents, "SGD"))
            }
          />
        </div>
      </section>

      <section className="card analytics-card category-analysis">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Allocation</p>
            <h2>Confirmed by Category</h2>
          </div>
          <span className="muted">Last six months</span>
        </div>
        <div className="category-analysis-body">
          {categoryData.length === 0 ? (
            <p className="empty">No confirmed Expenses in this period.</p>
          ) : (
            <>
              <DitherDonutChart
                data={categoryData}
                size={184}
                ariaLabel="Six-month confirmed spending by category"
              />
              <div className="cat-list">
                {categoryData.map((category) => (
                  <div
                    className="cat-row analytics-category"
                    key={category.label}
                  >
                    <span>
                      <i
                        className="swatch"
                        style={{ backgroundColor: category.color }}
                      />
                      {category.label}
                    </span>
                    <span className="amount">
                      {formatUnsigned(centsToMoney(category.value, "SGD"))}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
