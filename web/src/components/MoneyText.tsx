import { splitMoneyText } from "../lib/money";

export function MoneyText({ text }: { text: string }) {
  const parts = splitMoneyText(text);
  if (parts === null) {
    return <span className="money-value">{text}</span>;
  }
  return (
    <span className="money-figure">
      <span className="sr-only">{text}</span>
      <span className="money-currency" aria-hidden="true">
        {parts.currency}{" "}
      </span>
      <span className="money-value" aria-hidden="true">
        {parts.figure}
      </span>
    </span>
  );
}
