import type { CSSProperties } from "react";

import { categoryColor, categoryPrimary } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import { CategoryChip } from "./ui/CategoryChip";

export function CategoryRankList({
  categories,
  currency,
  onSelect,
  limit,
  figures = "both",
  showMeter = true,
}: {
  categories: Array<{ name: string; cents: number }>;
  currency: string;
  onSelect?: (name: string) => void;
  limit?: number;
  figures?: "amount" | "both";
  showMeter?: boolean;
}) {
  const total = categories.reduce((sum, item) => sum + item.cents, 0);
  if (categories.length === 0) {
    return <p className="empty">No confirmed Expenses in this month yet.</p>;
  }
  const visible =
    limit === undefined ? categories : categories.slice(0, Math.max(0, limit));
  const hidden = categories.length - visible.length;
  return (
    <div className={`cat-list${figures === "amount" ? " is-amount" : ""}`}>
      {visible.map((item) => {
        const share = total === 0 ? 0 : Math.round((item.cents / total) * 100);
        const color = categoryColor(categoryPrimary(item.name));
        const row = (
          <>
            <CategoryChip name={item.name} />
            {showMeter ? (
              <span
                className="cat-meter"
                style={{ "--cat-color": color } as CSSProperties}
              >
                <i style={{ width: `${share}%` }} />
              </span>
            ) : null}
            <span className="cat-figures">
              {figures === "both" ? (
                <span className="cat-share">{share}%</span>
              ) : null}
              <span className="amount">
                {formatUnsigned(centsToMoney(item.cents, currency))}
              </span>
            </span>
          </>
        );
        if (onSelect === undefined) {
          return (
            <div
              className={`cat-row${showMeter ? "" : " is-plain"}`}
              key={item.name}
            >
              {row}
            </div>
          );
        }
        return (
          <button
            className={`cat-row${showMeter ? "" : " is-plain"}`}
            type="button"
            key={item.name}
            onClick={() => {
              onSelect(item.name);
            }}
          >
            {row}
          </button>
        );
      })}
      {hidden > 0 ? <p className="cat-more">{hidden} more</p> : null}
    </div>
  );
}
