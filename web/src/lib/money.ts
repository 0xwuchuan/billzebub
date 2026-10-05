import type { Money } from "../api";

export function amountToCents(amount: string): number {
  const negative = amount.startsWith("-");
  const absolute = negative ? amount.slice(1) : amount;
  const [whole = "0", fraction = ""] = absolute.split(".");
  const frac = `${fraction}00`.slice(0, 2);
  const cents = Number.parseInt(whole, 10) * 100 + Number.parseInt(frac, 10);
  return negative ? -cents : cents;
}

export function centsToMoney(cents: number, currency: string): Money {
  const negative = cents < 0;
  const absolute = Math.abs(cents);
  const whole = Math.floor(absolute / 100);
  const fraction = String(absolute % 100).padStart(2, "0");
  return {
    amount: `${negative ? "-" : ""}${whole}.${fraction}`,
    currency,
  };
}

export function formatMoney(money: Money, signed = false): string {
  const cents = amountToCents(money.amount);
  const negative = cents < 0;
  const sign = signed
    ? negative
      ? "−"
      : cents > 0
        ? "+"
        : ""
    : negative
      ? "−"
      : "";
  const absolute = negative ? money.amount.slice(1) : money.amount;
  const [whole = "0", fraction] = absolute.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimals = fraction === undefined ? "" : `.${fraction}`;
  return `${sign}${money.currency} ${grouped}${decimals}`;
}

export function formatUnsigned(money: Money): string {
  const cents = Math.abs(amountToCents(money.amount));
  return formatMoney(centsToMoney(cents, money.currency), false);
}

export function splitMoneyText(
  text: string,
): { currency: string; figure: string } | null {
  const match = /^((?:[+−-])?[A-Za-z]{3}) (.+)$/.exec(text);
  if (match === null) {
    return null;
  }
  return { currency: match[1] ?? text, figure: match[2] ?? "" };
}
