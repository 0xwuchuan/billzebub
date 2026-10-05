import { splitMoneyText } from "../lib/money";

export function MoneyText({
  text,
  hero = false,
}: {
  text: string;
  hero?: boolean;
}) {
  const parts = splitMoneyText(text);
  if (parts === null) {
    return <span className="money-value">{text}</span>;
  }
  return (
    <span className={`money-figure${hero ? " is-hero" : " is-row"}`}>
      <span className="sr-only">{text}</span>
      {hero ? (
        <span aria-hidden="true">
          {parts.currency} <span className="money-value">{parts.figure}</span>
        </span>
      ) : (
        <span aria-hidden="true">
          {parts.currency}
          {"\u00A0"}
          <span className="money-value">{parts.figure}</span>
        </span>
      )}
    </span>
  );
}
