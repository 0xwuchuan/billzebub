import type {
  AmbiguousMatchCandidate,
  AmbiguousMatchProvisional,
} from "../api";
import { dayMonthLabel } from "./labels";
import { formatMoney, formatUnsigned } from "./money";

export const MATCH_UNDO_MS = 6000;
export const MATCH_PAGE_SIZE = 5;

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export type MatchDetail = {
  label: string;
  value: string;
};

export type MatchCandidateModel = {
  id: string;
  rankLabel: string;
  best: boolean;
  disabled: boolean;
  matchedTo: string | null;
  why: string;
  merchant: string;
  merchantTitle: string;
  raw: string | null;
  merchantMatches: boolean;
  merchantDelta: string | null;
  amount: string;
  amountMatches: boolean;
  amountDelta: string | null;
  posted: string;
  postedShort: string;
  txn: string | null;
  dateMatches: boolean;
  dateDelta: string | null;
  card: string;
  cardMatches: boolean;
  cardDelta: string | null;
  statement: string;
  statementTitle: string;
  details: MatchDetail[];
};

export type MatchAnchorModel = {
  merchant: string;
  merchantTitle: string;
  amount: string;
  when: string;
  card: string;
  source: string;
  meta: string;
  details: MatchDetail[];
};

export type MatchReviewModel = {
  subline: string;
  anchor: MatchAnchorModel;
  candidates: MatchCandidateModel[];
  empty: boolean;
  single: boolean;
  primaryId: string | null;
  noneLabel: string;
};

export function matchReviewView(
  context: Record<string, unknown>,
): MatchReviewModel | null {
  const provisional = readProvisional(context.provisional);
  const candidates = readCandidates(context.candidates);
  if (provisional === null || candidates === null) {
    return null;
  }
  const ranked = candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort(
      (left, right) =>
        right.candidate.score - left.candidate.score ||
        left.index - right.index,
    )
    .map((item) => item.candidate);
  const anchorMerchant = merchantLabel(
    provisional.counterparty.normalized,
    provisional.counterparty.raw,
  );
  const anchorCard = cardLabel(provisional.cardAlias, provisional.last4);
  const anchorWhen = whenLabel(
    provisional.occurred_at.date,
    provisional.occurred_at.time,
  );
  const models = ranked.map((candidate, index) =>
    candidateModel(candidate, index, provisional),
  );
  const enabled = models.filter((candidate) => !candidate.disabled);
  const primary = enabled[0] ?? null;
  for (const candidate of models) {
    candidate.best =
      primary !== null && candidate.id === primary.id && models.length > 1;
  }
  const count = models.length;
  return {
    subline: subline(count, provisional.source),
    anchor: {
      merchant: anchorMerchant,
      merchantTitle: provisional.counterparty.raw?.trim() || anchorMerchant,
      amount: moneyLabel(provisional.amount, provisional.currency),
      when: anchorWhen,
      card: anchorCard,
      source: sourceLabel(provisional.source),
      meta: anchorMeta(
        anchorWhen,
        provisional.cardAlias,
        provisional.last4,
        sourceLabel(provisional.source),
      ),
      details: detailsFor([
        ["Claim", provisional.claim_id],
        ["Raw descriptor", provisional.counterparty.raw],
      ]),
    },
    candidates: models,
    empty: count === 0,
    single: count === 1,
    primaryId: primary?.id ?? null,
    noneLabel: count === 1 ? "Not this one" : "None of these",
  };
}

export function matchChoice(statementClaimId: string): string {
  return `match:${statementClaimId}`;
}

export function ordinal(rank: number): string {
  const mod100 = rank % 100;
  if (mod100 >= 11 && mod100 <= 13) {
    return `${rank}th`;
  }
  const mod10 = rank % 10;
  if (mod10 === 1) {
    return `${rank}st`;
  }
  if (mod10 === 2) {
    return `${rank}nd`;
  }
  if (mod10 === 3) {
    return `${rank}rd`;
  }
  return `${rank}th`;
}

type ProvisionalFields = AmbiguousMatchProvisional & {
  cardAlias: string | null;
};

function candidateModel(
  candidate: AmbiguousMatchCandidate & { matched_to?: string | null },
  index: number,
  provisional: ProvisionalFields,
): MatchCandidateModel {
  const merchant = merchantLabel(
    candidate.normalized_counterparty,
    candidate.raw_description,
  );
  const merchantMatches = merchantsMatch(
    provisional.counterparty.normalized,
    provisional.counterparty.raw,
    candidate.normalized_counterparty,
    candidate.raw_description,
  );
  const raw = mutedRaw(merchant, candidate.raw_description, merchantMatches);
  const amountMatches = amountsMatch(candidate, provisional);
  const dateMatches = candidate.day_delta === 0;
  const card = cardLabel(null, candidate.last4);
  const cardMatches = cardsMatch(provisional.last4, candidate.last4);
  const cardDelta = cardsDiffer(provisional.last4, candidate.last4)
    ? "other card"
    : null;
  const statement = statementLabel(candidate);
  const postedShort = candidate.posted_date
    ? dayMonthLabel(candidate.posted_date)
    : "No date";
  const txn =
    candidate.transaction_date !== null &&
    candidate.transaction_date !== candidate.posted_date
      ? `txn ${dayMonthLabel(candidate.transaction_date)}`
      : null;
  const matchedTo = candidate.matched_to?.trim() || null;
  return {
    id: candidate.statement_claim_id,
    rankLabel: ordinal(index + 1),
    best: false,
    disabled: matchedTo !== null,
    matchedTo,
    why: whyLine(candidate, provisional, cardMatches, cardDelta, statement),
    merchant,
    merchantTitle: candidate.raw_description?.trim() || merchant,
    raw,
    merchantMatches,
    merchantDelta: merchantMatches ? null : "merchant differs",
    amount: moneyLabel(candidate.amount, candidate.currency),
    amountMatches,
    amountDelta: amountDeltaLabel(candidate, provisional),
    posted: postedShort,
    postedShort,
    txn,
    dateMatches,
    dateDelta:
      candidate.day_delta === null || candidate.day_delta === 0
        ? null
        : dayDeltaLabel(candidate.day_delta),
    card,
    cardMatches,
    cardDelta,
    statement,
    statementTitle: statement,
    details: detailsFor([
      ["Claim", candidate.claim_id || candidate.statement_claim_id],
      ["Statement", candidate.statement_id],
      ["Statement identity", candidate.statement_identity],
      ["Raw descriptor", candidate.raw_description],
    ]),
  };
}

function whyLine(
  candidate: AmbiguousMatchCandidate,
  provisional: ProvisionalFields,
  cardMatches: boolean,
  cardDelta: string | null,
  statement: string,
): string {
  const parts: string[] = [];
  const amount = whyAmount(candidate, provisional);
  if (amount !== null) {
    parts.push(amount);
  }
  const day = whyDay(candidate.day_delta);
  if (day !== null) {
    parts.push(day);
  }
  if (cardMatches) {
    parts.push("Same card");
  } else if (cardDelta !== null) {
    parts.push("Different card");
  }
  if (cardDelta !== null && statement !== "" && statement !== "Statement") {
    parts.push(statement);
  }
  return parts.join(" · ");
}

function whyAmount(
  candidate: AmbiguousMatchCandidate,
  provisional: ProvisionalFields,
): string | null {
  if (amountsMatch(candidate, provisional)) {
    return "Exact amount";
  }
  if (
    candidate.amount_delta !== null &&
    candidate.currency !== null &&
    candidate.currency === provisional.currency
  ) {
    const money = formatUnsigned({
      amount: candidate.amount_delta,
      currency: candidate.currency,
    });
    return Number(candidate.amount_delta) > 0
      ? `${money} more`
      : `${money} less`;
  }
  if (
    candidate.currency !== null &&
    provisional.currency !== null &&
    candidate.currency !== provisional.currency
  ) {
    return "Different currency";
  }
  return null;
}

function whyDay(days: number | null): string | null {
  if (days === null) {
    return null;
  }
  if (days === 0) {
    return "Same day";
  }
  if (days === 1) {
    return "1 day later";
  }
  if (days === -1) {
    return "1 day earlier";
  }
  if (days > 1) {
    return `${days} days later`;
  }
  return `${Math.abs(days)} days earlier`;
}

function subline(count: number, source: string | null): string {
  if (count === 0) {
    return "";
  }
  const kind = source === "paylah" ? "PayLah charge" : "Apple Wallet charge";
  const noun = count === 1 ? "statement line" : "statement lines";
  return `${kind} matched ${count} ${noun}`;
}

function anchorMeta(
  when: string,
  alias: string | null,
  last4: string | null,
  source: string,
): string {
  const named = alias?.trim() ?? "";
  const card =
    named !== "" && last4 !== null
      ? `${named} ·· ${last4}`
      : cardLabel(alias, last4);
  return [when, card, source].filter((part) => part !== "").join(" · ");
}

function sourceLabel(source: string | null): string {
  if (source === "paylah") {
    return "PayLah";
  }
  return "Wallet";
}

function merchantLabel(normalized: string | null, raw: string | null): string {
  const name = normalized?.trim() ?? "";
  if (name !== "") {
    return titleCase(name);
  }
  const descriptor = raw?.trim() ?? "";
  return descriptor === "" ? "Unknown counterparty" : descriptor;
}

function merchantsMatch(
  anchorNormalized: string | null,
  anchorRaw: string | null,
  candidateNormalized: string | null,
  candidateRaw: string | null,
): boolean {
  const anchor = (anchorNormalized ?? anchorRaw ?? "").trim().toLowerCase();
  const candidate = (candidateNormalized ?? candidateRaw ?? "")
    .trim()
    .toLowerCase();
  return anchor !== "" && anchor === candidate;
}

function mutedRaw(
  merchant: string,
  raw: string | null,
  matches: boolean,
): string | null {
  if (matches) {
    return null;
  }
  const descriptor = raw?.trim() ?? "";
  if (
    descriptor === "" ||
    descriptor.toLowerCase() === merchant.toLowerCase()
  ) {
    return null;
  }
  return descriptor;
}

function amountsMatch(
  candidate: AmbiguousMatchCandidate,
  provisional: ProvisionalFields,
): boolean {
  return (
    candidate.currency !== null &&
    candidate.currency === provisional.currency &&
    isZero(candidate.amount_delta)
  );
}

function amountDeltaLabel(
  candidate: AmbiguousMatchCandidate,
  provisional: ProvisionalFields,
): string | null {
  if (amountsMatch(candidate, provisional) || candidate.currency === null) {
    return null;
  }
  if (
    candidate.amount_delta !== null &&
    candidate.currency === provisional.currency
  ) {
    return formatMoney(
      { amount: candidate.amount_delta, currency: candidate.currency },
      true,
    );
  }
  if (
    provisional.currency !== null &&
    candidate.currency !== provisional.currency
  ) {
    return "different currency";
  }
  return null;
}

function cardsMatch(anchor: string | null, candidate: string | null): boolean {
  return anchor !== null && anchor === candidate;
}

function cardsDiffer(anchor: string | null, candidate: string | null): boolean {
  if (anchor === null && candidate === null) {
    return false;
  }
  return anchor !== candidate;
}

function cardLabel(alias: string | null, last4: string | null): string {
  if (alias !== null && alias.trim() !== "" && last4 !== null) {
    return `${alias.trim()} · ${last4}`;
  }
  if (last4 !== null) {
    return `···· ${last4}`;
  }
  if (alias !== null && alias.trim() !== "") {
    return alias.trim();
  }
  return "No card";
}

function statementLabel(candidate: AmbiguousMatchCandidate): string {
  const name =
    candidate.statement_label?.trim() || titleCase(candidate.issuer ?? "");
  const period = periodLabel(candidate.period_start, candidate.period_end);
  if (name !== "" && period !== null) {
    return `${name} · ${period}`;
  }
  return name || period || "Statement";
}

export function periodLabel(
  start: string | null,
  end: string | null,
): string | null {
  if (start === null && end === null) {
    return null;
  }
  if (start !== null && end !== null) {
    const startParts = start.split("-");
    const endParts = end.split("-");
    const startMonth = Number(startParts[1]);
    const endMonth = Number(endParts[1]);
    if (
      startParts[0] === endParts[0] &&
      startParts[1] === endParts[1] &&
      startMonth >= 1 &&
      startMonth <= 12
    ) {
      return `${Number(startParts[2])}–${Number(endParts[2])} ${MONTHS[startMonth - 1]}`;
    }
    if (endMonth >= 1) {
      return `${dayMonthLabel(start)} – ${dayMonthLabel(end)}`;
    }
  }
  const only = start ?? end;
  return only === null ? null : dayMonthLabel(only);
}

function whenLabel(date: string | null, time: string | null): string {
  const day = date === null || date === "" ? "No date" : dayMonthLabel(date);
  const clock = clockLabel(time);
  return clock === null ? day : `${day} · ${clock}`;
}

function clockLabel(time: string | null): string | null {
  if (time === null) {
    return null;
  }
  const match = /^(\d{2}):(\d{2})/.exec(time);
  if (match === null) {
    return null;
  }
  return `${match[1]}:${match[2]}`;
}

function moneyLabel(amount: string | null, currency: string | null): string {
  if (amount === null || currency === null || amount === "") {
    return "—";
  }
  return formatUnsigned({ amount, currency });
}

function dayDeltaLabel(days: number): string {
  const absolute = Math.abs(days);
  const unit = absolute === 1 ? "day" : "days";
  const sign = days > 0 ? "+" : "−";
  return `${sign}${absolute} ${unit}`;
}

function isZero(value: string | null): boolean {
  if (value === null) {
    return false;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed === 0;
}

function titleCase(value: string): string {
  return value.replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

function detailsFor(rows: [string, string | null][]): MatchDetail[] {
  return rows.flatMap(([label, value]) => {
    const text = value?.trim() ?? "";
    return text === "" ? [] : [{ label, value: text }];
  });
}

function readProvisional(value: unknown): ProvisionalFields | null {
  if (!isRecord(value) || typeof value.claim_id !== "string") {
    return null;
  }
  const counterparty = isRecord(value.counterparty) ? value.counterparty : {};
  const occurred = isRecord(value.occurred_at) ? value.occurred_at : {};
  const source = value.source;
  return {
    claim_id: value.claim_id,
    counterparty: {
      raw: optionalString(counterparty.raw),
      normalized: optionalString(counterparty.normalized),
    },
    amount: optionalString(value.amount),
    currency: optionalString(value.currency),
    occurred_at: {
      date: optionalString(occurred.date),
      time: optionalString(occurred.time),
      timezone: typeof occurred.timezone === "string" ? occurred.timezone : "",
    },
    last4: optionalString(value.last4),
    source: source === "wallet" || source === "paylah" ? source : null,
    cardAlias: optionalString(value.card_alias),
  };
}

function readCandidates(value: unknown): AmbiguousMatchCandidate[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const candidates: AmbiguousMatchCandidate[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.statement_claim_id !== "string") {
      return null;
    }
    const reasons = Array.isArray(item.match_reasons) ? item.match_reasons : [];
    candidates.push({
      statement_claim_id: item.statement_claim_id,
      claim_id:
        typeof item.claim_id === "string"
          ? item.claim_id
          : item.statement_claim_id,
      score: typeof item.score === "number" ? item.score : 0,
      reasons: Array.isArray(item.reasons)
        ? item.reasons.filter(
            (reason): reason is string => typeof reason === "string",
          )
        : [],
      raw_description: optionalString(item.raw_description),
      normalized_counterparty: optionalString(item.normalized_counterparty),
      amount: optionalString(item.amount),
      currency: optionalString(item.currency),
      posted_date: optionalString(item.posted_date),
      transaction_date: optionalString(item.transaction_date),
      last4: optionalString(item.last4),
      statement_id: optionalString(item.statement_id),
      statement_identity: optionalString(item.statement_identity),
      statement_label: optionalString(item.statement_label),
      issuer: optionalString(item.issuer),
      period_start: optionalString(item.period_start),
      period_end: optionalString(item.period_end),
      amount_delta: optionalString(item.amount_delta),
      day_delta: typeof item.day_delta === "number" ? item.day_delta : null,
      match_reasons: reasons.flatMap((reason) => {
        if (!isRecord(reason) || typeof reason.code !== "string") {
          return [];
        }
        const criterion = reason.criterion;
        return [
          {
            criterion:
              criterion === "financial_account" ||
              criterion === "amount" ||
              criterion === "date" ||
              criterion === "counterparty" ||
              criterion === "other"
                ? criterion
                : "other",
            passed: reason.passed === true,
            code: reason.code,
          },
        ];
      }),
      matched_to: optionalString(item.matched_to),
    });
  }
  return candidates;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
