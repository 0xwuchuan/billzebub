const EMAIL = /^([^\s@]+)@([^\s@]+\.[^\s@]+)$/;
const URL_SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;
const FILE_EXT =
  /\.(heic|jpe?g|png|gif|webp|pdf|csv|txt|zip|json|xml|ofx|qfx|xlsx?|numbers)$/i;

export const UNKNOWN_COUNTERPARTY = "Unknown counterparty";

export type IdentityShape =
  | { kind: "empty" }
  | { kind: "plain"; text: string }
  | { kind: "url"; text: string }
  | { kind: "email"; local: string; domain: string }
  | { kind: "file"; stem: string; ext: string };

export function describeIdentity(value: string): IdentityShape {
  const trimmed = value.trim();
  if (trimmed === "") {
    return { kind: "empty" };
  }
  const email = EMAIL.exec(trimmed);
  if (email !== null) {
    return { kind: "email", local: email[1] ?? "", domain: email[2] ?? "" };
  }
  const bare = stripUrlScheme(trimmed);
  if (bare !== null) {
    return { kind: "url", text: bare };
  }
  const file = splitFilename(trimmed);
  if (file !== null) {
    return { kind: "file", stem: file.stem, ext: file.ext };
  }
  return { kind: "plain", text: trimmed };
}

export function stripUrlScheme(value: string): string | null {
  const trimmed = value.trim();
  if (!URL_SCHEME.test(trimmed)) {
    return null;
  }
  return trimmed.replace(URL_SCHEME, "");
}

export function formatAccountLabel(value: string): string {
  const trimmed = value.trim();
  return stripUrlScheme(trimmed) ?? trimmed;
}

function splitFilename(value: string): { stem: string; ext: string } | null {
  if (/\s/.test(value) || value.includes("/")) {
    return null;
  }
  const match = FILE_EXT.exec(value);
  if (match === null || match.index <= 0) {
    return null;
  }
  return {
    stem: value.slice(0, match.index),
    ext: value.slice(match.index + 1),
  };
}

export function splitFileTail(
  value: string,
  tailChars = 14,
): { lead: string; tail: string } | null {
  const file = splitFilename(value.trim());
  if (file !== null) {
    return { lead: file.stem, tail: `.${file.ext}` };
  }
  const trimmed = value.trim();
  if (trimmed.length <= tailChars + 8) {
    return null;
  }
  return {
    lead: trimmed.slice(0, trimmed.length - tailChars),
    tail: trimmed.slice(-tailChars),
  };
}

export function claimCountLabel(count: number): string {
  return `${count} ${count === 1 ? "claim" : "claims"}`;
}

export function counterpartyText(value: string): string {
  return value.trim() === "" ? UNKNOWN_COUNTERPARTY : value;
}
