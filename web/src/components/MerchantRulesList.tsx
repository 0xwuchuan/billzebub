import type { MerchantRule } from "../api";

export function MerchantRulesList({ rules }: { rules: MerchantRule[] }) {
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
      {rules.map((rule) => (
        <li key={`${rule.source}:${rule.normalized_key}`}>
          <span className="merchant-rule-name">
            {rule.label ?? titleCase(rule.normalized_key)}
          </span>
          <span>{rule.category_name}</span>
          <span className="muted">
            {rule.source === "owner" ? "Owner" : "Jev"}
          </span>
        </li>
      ))}
    </ul>
  );
}

function titleCase(value: string): string {
  return value.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}
