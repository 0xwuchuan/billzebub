import { useId } from "react";

import type { RecurringSummary, Transaction } from "../api";
import { CategoryRankList } from "../components/CategoryRankList";
import {
  DitherBarChart,
  DitherDonutChart,
} from "../components/dither-kit/DitherCharts";
import { TxRow } from "../components/TxRow";
import { useEntrance } from "../hooks/useEntrance";
import { CONFIRMATION_SERIES } from "../lib/chartSeries";
import { categoryColor, categoryPrimary } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import { recurringAmountLabel, relativeDueLabel } from "../lib/recurrings";
import {
  categoryTotals,
  monthTotals,
  reportingPeriod,
  sortTransactions,
  weekComparison,
} from "../lib/workspace";

const RECENT_LIMIT = 5;

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
  summary,
  proposedCount,
  onOpenRecurrings,
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
  summary: RecurringSummary | null;
  proposedCount: number;
  onOpenRecurrings: () => void;
}) {
  const fresh = useEntrance("overview");
  const monthId = useId();
  const attentionId = useId();
  const categoriesId = useId();
  const recentId = useId();
  const recurringId = useId();
  const period = reportingPeriod(transactions, today);
  const totals = monthTotals(transactions, period);
  const categories = categoryTotals(transactions, period);
  const week = weekComparison(transactions, today).map((day) => ({
    label: day.label,
    confirmed: day.confirmedCents,
    provisional: day.provisionalCents,
  }));
  const recent = sortTransactions(transactions).slice(0, RECENT_LIMIT);
  const pending = Math.max(0, reviewCount);
  return (
    <div className={`dash-grid${fresh ? " stage-enter" : ""}`}>
      <div className="bento-top">
        <section
          className="card dash-card bento-hero"
          aria-labelledby={monthId}
        >
          <div className="bento-hero-body">
            <h2 id={monthId} className="eyebrow">
              This month
            </h2>
            <div className="bento-hero-main">
              <div className="bento-hero-copy">
                <p className="bento-figure amount">
                  {formatUnsigned(
                    centsToMoney(totals.estimatedCents, totals.currency),
                  )}
                </p>
                <p className="bento-hero-foot">
                  <button
                    type="button"
                    title="Transactions with a Posted Amount"
                    onClick={onFilterConfirmed}
                  >
                    <i className="cell-dot confirmed" aria-hidden="true" />
                    Confirmed
                    <span className="amount">
                      {formatUnsigned(
                        centsToMoney(totals.confirmedCents, totals.currency),
                      )}
                    </span>
                  </button>
                  <span className="bento-foot-sep" aria-hidden="true">
                    ·
                  </span>
                  <button
                    type="button"
                    title="Awaiting a Statement Claim"
                    onClick={onFilterProvisional}
                  >
                    <i className="cell-dot provisional" aria-hidden="true" />
                    Provisional
                    <span className="amount">
                      {formatUnsigned(
                        centsToMoney(totals.provisionalCents, totals.currency),
                      )}
                    </span>
                  </button>
                </p>
              </div>
              <div className="dash-week">
                <p className="dash-caption">This week</p>
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
            </div>
          </div>
        </section>

        <section
          className={`card dash-card bento-attention${pending > 0 ? " has-queue" : ""}`}
          aria-labelledby={attentionId}
        >
          <h2 id={attentionId} className="eyebrow">
            Attention
          </h2>
          <button
            className="bento-attention-hit"
            type="button"
            onClick={onOpenReview}
          >
            <span className="bento-attention-count amount">{reviewCount}</span>
            <span className="bento-attention-line">
              <span>{attentionLine(reviewCount, blockingCount)}</span>
              <span className="bento-link">Review →</span>
            </span>
          </button>
        </section>
      </div>

      {summary !== null ? (
        <section
          className="card dash-card bento-recurring"
          aria-labelledby={recurringId}
        >
          <button
            className="recurring-strip"
            type="button"
            aria-label={
              proposedCount > 0
                ? `Recurrings, ${formatUnsigned(summary.total)} this month, ${proposedCount} to review`
                : `Recurrings, ${formatUnsigned(summary.total)} this month`
            }
            onClick={onOpenRecurrings}
          >
            <span className="recurring-strip-head">
              <span id={recurringId} className="eyebrow">
                Recurring
              </span>
              <span className="bento-link">Recurrings →</span>
            </span>
            <span className="recurring-strip-line">
              <span className="recurring-strip-figure">
                <span className="recurring-strip-total amount">
                  {formatUnsigned(summary.total)}
                </span>
                <span className="recurring-meta">this month</span>
              </span>
              <span className="recurring-due-list">
                {summary.upcoming.slice(0, 3).map((series) => (
                  <span className="recurring-due" key={series.id}>
                    <span className="recurring-due-name">
                      {series.counterparty}
                    </span>
                    <span className="recurring-meta">
                      {relativeDueLabel(series.next_expected_date, today)}
                    </span>
                    <span className="amount">
                      {recurringAmountLabel(series.amount)}
                    </span>
                  </span>
                ))}
              </span>
            </span>
            {proposedCount > 0 ? (
              <span className="recurring-review-cue">
                {proposedCount} to review
              </span>
            ) : null}
          </button>
        </section>
      ) : null}

      <div className="bento-bottom">
        <article
          className="card dash-card bento-categories"
          aria-labelledby={categoriesId}
        >
          <div className="bento-head">
            <h2 id={categoriesId} className="eyebrow">
              Top categories
            </h2>
          </div>
          <div className="bento-cat-body">
            {categories.length === 0 ? null : (
              <DitherDonutChart
                data={categories.map((item) => ({
                  label: item.name,
                  value: item.cents,
                  color: categoryColor(categoryPrimary(item.name)),
                }))}
                size={88}
                ariaLabel="Spending by category this month"
              />
            )}
            <CategoryRankList
              categories={categories}
              currency={totals.currency}
              limit={5}
              figures="amount"
              showMeter={false}
              onSelect={onFilterCategory}
            />
          </div>
        </article>

        <section
          className="card dash-card bento-recent recent"
          aria-labelledby={recentId}
        >
          <div className="bento-head">
            <h2 id={recentId} className="eyebrow">
              Recent
            </h2>
            <button
              className="bento-link"
              type="button"
              onClick={onOpenTransactions}
            >
              All transactions →
            </button>
          </div>
          {recent.length === 0 ? (
            <p className="empty">
              No trusted Transactions yet. Process an accepted statement to
              begin.
            </p>
          ) : (
            recent.map((transaction) => (
              <TxRow
                key={transaction.id}
                transaction={transaction}
                density="compact"
                provisionalMark="dot"
                onOpen={onOpenTransaction}
              />
            ))
          )}
        </section>
      </div>
    </div>
  );
}

function attentionLine(reviewCount: number, blockingCount: number): string {
  if (reviewCount <= 0) {
    return "Queue is clear";
  }
  const attention = Math.max(0, reviewCount - blockingCount);
  const parts: string[] = [];
  if (blockingCount > 0) {
    parts.push(`${blockingCount} blocking`);
  }
  if (attention > 0) {
    parts.push(`${attention} attention`);
  }
  return parts.join(" · ");
}
