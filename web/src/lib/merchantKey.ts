const NOISE = new Set([
  "card",
  "co",
  "com",
  "credit",
  "debit",
  "inc",
  "ltd",
  "mastercard",
  "payment",
  "posted",
  "pte",
  "purchase",
  "sg",
  "sgd",
  "singapore",
  "transaction",
  "visa",
  "www",
]);

/** Same merchant key the API uses: NFKD, ascii, casefold, drop noise and refs. */
export function merchantKey(value: string): string {
  const folded = asciiFold(value).toLowerCase();
  const tokens = folded.match(/[a-z0-9]+/g) ?? [];
  return tokens
    .filter(
      (token) =>
        !NOISE.has(token) &&
        !/^\d+$/.test(token) &&
        token.length > 1 &&
        !opaqueRef(token),
    )
    .join(" ")
    .slice(0, 300);
}

function asciiFold(value: string): string {
  const normalized = value.normalize("NFKD");
  let ascii = "";
  for (const character of normalized) {
    if (character.charCodeAt(0) < 128) {
      ascii += character;
    }
  }
  return ascii;
}

function opaqueRef(token: string): boolean {
  if (!/^[a-z]*\d[a-z0-9]{6,}$/.test(token)) {
    return false;
  }
  if (/[a-z]{4,}/.test(token)) {
    return false;
  }
  const digits = [...token].filter(
    (character) => character >= "0" && character <= "9",
  ).length;
  return /[a-z]/.test(token) && digits >= 3;
}
