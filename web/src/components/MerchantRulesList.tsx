import type { MerchantRule } from "../api";
import { CategoryChip } from "./ui/CategoryChip";

export function MerchantRulesList({
  rules,
  onRemove,
}: {
  rules: MerchantRule[];
  onRemove?: (normalizedKey: string) => void;
}) {
  if (rules.length === 0) {
    return (
      <p className="empty">
        No merchant rules yet. Apply a group from Review to teach future
        charges.
      </p>
    );
  }
  return (
    <ul className="merchant-rules">
      {rules.map((rule) => {
        const name = rule.label ?? titleCase(rule.normalized_key);
        return (
          <li
            key={`${rule.source}:${rule.normalized_key}`}
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Delete" || event.key === "Backspace") {
                event.preventDefault();
                onRemove?.(rule.normalized_key);
              }
            }}
          >
            <span className="merchant-rule-name">{name}</span>
            <CategoryChip name={rule.category_name} />
            <span className="merchant-rule-source">
              {rule.source === "owner" ? "Owner" : "Jev"}
            </span>
            <button
              className="merchant-rule-remove"
              type="button"
              aria-label={`Remove ${name}`}
              onClick={() => {
                onRemove?.(rule.normalized_key);
              }}
            >
              Remove
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function titleCase(value: string): string {
  return value.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}
