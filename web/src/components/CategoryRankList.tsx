import type { CSSProperties } from "react";

import { categoryColor, categoryPrimary } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import { CategoryChip } from "./ui/CategoryChip";

export function CategoryRankList({
  categories,
  currency,
  onSelect,
}: {
  categories: Array<{ name: string; cents: number }>;
  currency: string;
  onSelect?: (name: string) => void;
}) {
  const total = categories.reduce((sum, item) => sum + item.cents, 0);
  if (categories.length === 0) {
    return <p className="empty">No confirmed Expenses in this month yet.</p>;
  }
  return (
    <div className="cat-list">
      {categories.map((item) => {
        const share = total === 0 ? 0 : Math.round((item.cents / total) * 100);
        const color = categoryColor(categoryPrimary(item.name));
        const row = (
          <>
            <CategoryChip name={item.name} />
            <span
              className="cat-meter"
              style={{ "--cat-color": color } as CSSProperties}
            >
              <i style={{ width: `${share}%` }} />
            </span>
            <span className="cat-figures">
              <span className="cat-share">{share}%</span>
              <span className="amount">
                {formatUnsigned(centsToMoney(item.cents, currency))}
              </span>
            </span>
          </>
        );
        if (onSelect === undefined) {
          return (
            <div className="cat-row" key={item.name}>
              {row}
            </div>
          );
        }
        return (
          <button
            className="cat-row"
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
    </div>
  );
}
