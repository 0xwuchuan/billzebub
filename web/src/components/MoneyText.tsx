import { splitMoneyText } from "../lib/money";

export function MoneyText({
  text,
  hero = false,
  glue = false,
}: {
  text: string;
  hero?: boolean;
  glue?: boolean;
}) {
  const parts = splitMoneyText(text);
  if (parts === null) {
    return <span className="money-value">{text}</span>;
  }
  const joined = !hero || glue;
  return (
    <span className={`money-figure${hero ? " is-hero" : " is-row"}`}>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {parts.currency}
        {joined ? "\u00A0" : " "}
        <span className="money-value">{parts.figure}</span>
      </span>
    </span>
  );
}
