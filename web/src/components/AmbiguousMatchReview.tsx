import { useEffect, useRef, useState, type ReactNode } from "react";

import { CategoryChip } from "./ui/CategoryChip";
import { Button } from "./ui/Button";
import { MoneyText } from "./MoneyText";
import { UserLabel } from "./UserLabel";
import { useDeskMedia } from "../hooks/useDeskMedia";
import {
  MATCH_PAGE_SIZE,
  matchChoice,
  matchReviewView,
  type MatchCandidateModel,
  type MatchReviewModel,
} from "../lib/ambiguousMatch";

export function AmbiguousMatchReview({
  context,
  categoryName = null,
  pending = false,
  onMatch,
  onReject,
  onOpenTransaction,
}: {
  context: Record<string, unknown>;
  categoryName?: string | null;
  pending?: boolean;
  onMatch: (choice: string) => void;
  onReject: () => void;
  onOpenTransaction: () => void;
}) {
  const model = matchReviewView(context);
  const phone = !useDeskMedia();
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState(() =>
    model === null ? 0 : firstEnabled(model.candidates),
  );
  const visible =
    model === null
      ? []
      : expanded
        ? model.candidates
        : model.candidates.slice(0, MATCH_PAGE_SIZE);
  const hidden = model === null ? 0 : model.candidates.length - visible.length;
  const bounded = Math.min(selected, Math.max(visible.length - 1, 0));
  const actionRef = useRef({
    confirmSelected: () => {},
    onReject,
    hidden,
    length: visible.length,
    pending,
    active: model !== null,
  });

  useEffect(() => {
    actionRef.current = {
      confirmSelected: () => {
        const candidate = visible[bounded];
        if (candidate !== undefined && !candidate.disabled && !pending) {
          onMatch(matchChoice(candidate.id));
          return;
        }
        if (model?.primaryId != null && !pending) {
          onMatch(matchChoice(model.primaryId));
        }
      },
      onReject,
      hidden,
      length: visible.length,
      pending,
      active: model !== null,
    };
  });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const action = actionRef.current;
      if (
        !action.active ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        event.isComposing ||
        isTyping(event.target)
      ) {
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        event.stopImmediatePropagation();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        setSelected((current) => {
          const start = Math.min(current, Math.max(action.length - 1, 0));
          return Math.min(action.length - 1, Math.max(0, start + delta));
        });
        return;
      }
      if (/^[1-9]$/.test(event.key)) {
        const index = Number(event.key) - 1;
        if (index >= action.length) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        setSelected(index);
        return;
      }
      if (event.key === "m" || event.key === "M") {
        if (action.hidden <= 0) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        setExpanded(true);
        return;
      }
      if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!action.pending) {
          action.onReject();
        }
        return;
      }
      if (event.key === "Enter") {
        if (isActivationTarget(event.target)) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        action.confirmSelected();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
    };
  }, []);

  if (model === null) {
    return null;
  }

  function confirmAt(index: number) {
    const candidate = visible[index];
    if (candidate === undefined || candidate.disabled || pending) {
      return;
    }
    onMatch(matchChoice(candidate.id));
  }

  const dockCandidate = dockChoice(model, visible[bounded]);
  return (
    <div className={`match-review${phone ? " is-phone" : ""}`}>
      <header className="match-head">
        <h2>Which statement line is this?</h2>
        {model.subline === "" ? null : <p className="muted">{model.subline}</p>}
      </header>
      <article className="match-anchor">
        <div className="match-anchor-row">
          <div
            className="match-anchor-merchant"
            title={model.anchor.merchantTitle}
          >
            <UserLabel value={model.anchor.merchant} />
            {categoryName === null ? null : (
              <CategoryChip name={categoryName} />
            )}
          </div>
          <p className="match-amount amount">
            <i className="provisional-dot" aria-hidden="true" />
            <MoneyText glue hero text={model.anchor.amount} />
          </p>
        </div>
        <p className="match-anchor-meta">{model.anchor.meta}</p>
        <DetailList rows={model.anchor.details} />
      </article>
      {model.empty ? (
        <div className="match-empty">
          <p>No statement lines left to match.</p>
          <p>Keep it as a Wallet charge?</p>
        </div>
      ) : (
        <div
          className="match-list"
          role={phone ? "radiogroup" : "list"}
          aria-label="Statement lines"
        >
          {visible.map((candidate, index) => (
            <CandidateCard
              key={candidate.id}
              candidate={candidate}
              phone={phone}
              selected={index === bounded}
              pending={pending}
              primary={candidate.id === model.primaryId}
              single={model.single}
              onSelect={() => {
                setSelected(index);
              }}
              onMatch={() => {
                confirmAt(index);
              }}
            />
          ))}
          {hidden > 0 ? (
            <Button
              variant="ghost"
              onClick={() => {
                setExpanded(true);
              }}
            >
              Show {hidden} more
            </Button>
          ) : null}
        </div>
      )}
      <ul className="review-shortcuts" aria-label="Keyboard shortcuts">
        <li>
          <kbd>1</kbd>–<kbd>9</kbd> select
        </li>
        <li>
          <kbd>Enter</kbd> confirms
        </li>
        <li>
          <kbd>N</kbd>{" "}
          {model.empty ? "keep the Wallet charge" : model.noneLabel}
        </li>
        <li>
          <kbd>↑</kbd>
          <kbd>↓</kbd> move
        </li>
        <li>
          <kbd>M</kbd> show more
        </li>
        <li>
          <kbd>Z</kbd> undo
        </li>
      </ul>
      {model.empty ? (
        <div className={phone ? "match-none" : "match-footer"}>
          {phone ? null : (
            <Button variant="primary" disabled={pending} onClick={onReject}>
              Keep as Wallet charge
            </Button>
          )}
          <Button variant="ghost" onClick={onOpenTransaction}>
            Open transaction
          </Button>
        </div>
      ) : phone ? (
        <div className="match-none">
          <Button variant="ghost" disabled={pending} onClick={onReject}>
            {model.noneLabel}
          </Button>
        </div>
      ) : (
        <div className="match-footer">
          <Button
            variant={model.primaryId === null ? "primary" : "ghost"}
            disabled={pending}
            onClick={onReject}
          >
            {model.noneLabel}
          </Button>
        </div>
      )}
      {phone ? (
        <div className="merchant-save-dock">
          <Button
            variant="primary"
            disabled={pending || (!model.empty && dockCandidate === null)}
            onClick={() => {
              if (model.empty || dockCandidate === null) {
                onReject();
                return;
              }
              onMatch(matchChoice(dockCandidate.id));
            }}
          >
            <span className="decision-choice">
              {dockLabel(model, dockCandidate)}
            </span>
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function CandidateCard({
  candidate,
  phone,
  selected,
  pending,
  primary,
  single,
  onSelect,
  onMatch,
}: {
  candidate: MatchCandidateModel;
  phone: boolean;
  selected: boolean;
  pending: boolean;
  primary: boolean;
  single: boolean;
  onSelect: () => void;
  onMatch: () => void;
}) {
  const className = `match-card${selected ? " is-selected" : ""}${candidate.disabled ? " is-disabled" : ""}`;
  const body = (
    <>
      <div className="match-card-top">
        {phone ? <span className="match-radio" aria-hidden="true" /> : null}
        <span className="match-rank">
          {candidate.best ? (
            <span className="match-best">Best match</span>
          ) : null}
          <span className="match-place">{candidate.rankLabel}</span>
        </span>
      </div>
      <div className="match-fields">
        <Field
          matches={candidate.merchantMatches}
          delta={candidate.merchantDelta}
          title={candidate.merchantTitle}
        >
          <UserLabel value={candidate.merchant} />
          {candidate.raw === null ? null : (
            <span className="match-raw" title={candidate.raw}>
              {candidate.raw}
            </span>
          )}
        </Field>
        <Field matches={candidate.amountMatches} delta={candidate.amountDelta}>
          <MoneyText text={candidate.amount} />
        </Field>
        <Field matches={candidate.dateMatches} delta={candidate.dateDelta}>
          <span>{candidate.posted}</span>
          {candidate.txn === null ? null : (
            <span className="match-txn">{candidate.txn}</span>
          )}
        </Field>
        <Field
          className="is-card"
          matches={candidate.cardMatches}
          delta={candidate.cardDelta}
        >
          <span>{candidate.card}</span>
        </Field>
        <div className="match-field is-note" title={candidate.statementTitle}>
          <span className="match-field-value">{candidate.statement}</span>
        </div>
      </div>
      {candidate.why === "" ? null : (
        <p className="match-why">{candidate.why}</p>
      )}
      {candidate.disabled ? (
        <p className="match-taken">
          Already matched to {candidate.matchedTo} (Undo there)
        </p>
      ) : phone ? null : (
        <Button
          variant={primary ? "primary" : "ghost"}
          disabled={pending}
          onClick={onMatch}
        >
          <span className="decision-choice">
            {primary ? (single ? "Match" : "Match to this") : "This one"}
          </span>
        </Button>
      )}
      <DetailList rows={candidate.details} />
    </>
  );
  if (!phone) {
    return (
      <article
        className={className}
        aria-current={selected ? "true" : undefined}
        onClick={onSelect}
      >
        {body}
      </article>
    );
  }
  return (
    <div
      className={className}
      role="radio"
      aria-checked={selected}
      aria-disabled={candidate.disabled}
      tabIndex={candidate.disabled ? -1 : 0}
      onClick={() => {
        if (!candidate.disabled) {
          onSelect();
        }
      }}
      onKeyDown={(event) => {
        if (candidate.disabled) {
          return;
        }
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      {body}
    </div>
  );
}

function Field({
  matches,
  delta,
  title,
  className = "",
  children,
}: {
  matches: boolean;
  delta: string | null;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`match-field${matches ? " is-same" : " is-diff"}${className === "" ? "" : ` ${className}`}`}
      title={title}
    >
      <span className="match-field-value">
        {children}
        {delta === null ? null : <span className="match-delta">{delta}</span>}
      </span>
    </div>
  );
}

function DetailList({ rows }: { rows: { label: string; value: string }[] }) {
  if (rows.length === 0) {
    return null;
  }
  return (
    <details className="match-details">
      <summary>Details</summary>
      <dl>
        {rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd className="match-mono">{row.value}</dd>
            <button
              className="match-copy"
              type="button"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void navigator.clipboard?.writeText(row.value);
              }}
            >
              Copy
            </button>
          </div>
        ))}
      </dl>
    </details>
  );
}

function dockChoice(
  model: MatchReviewModel,
  selected: MatchCandidateModel | undefined,
): MatchCandidateModel | null {
  if (selected !== undefined && !selected.disabled) {
    return selected;
  }
  return (
    model.candidates.find((candidate) => candidate.id === model.primaryId) ??
    null
  );
}

function dockLabel(
  model: MatchReviewModel,
  candidate: MatchCandidateModel | null,
): string {
  if (model.empty) {
    return "Keep as Wallet charge";
  }
  if (model.single && model.primaryId !== null) {
    return "Match";
  }
  if (candidate === null) {
    return model.noneLabel;
  }
  return `Match to ${candidate.merchant} · ${candidate.postedShort}`;
}

function firstEnabled(candidates: MatchCandidateModel[]): number {
  const index = candidates.findIndex((candidate) => !candidate.disabled);
  return index < 0 ? 0 : index;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function isActivationTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element && target.closest("button, a, summary") !== null
  );
}
