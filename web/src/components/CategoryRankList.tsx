import {
  useEffect,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";

import { MoneyText } from "./MoneyText";
import { categoryColor, categoryPrimary } from "../lib/labels";
import { centsToMoney, formatUnsigned } from "../lib/money";
import type { SpendGroup } from "../lib/categoryTree";
import { useOverlayMedia } from "../hooks/useOverlayMedia";
import { CategoryChip } from "./ui/CategoryChip";

export function CategoryRankList({
  categories,
  groups,
  currency,
  onSelect,
  onOpenFilter,
  limit,
  figures = "both",
  showMeter = true,
}: {
  categories: Array<{ name: string; cents: number }>;
  groups?: SpendGroup[] | undefined;
  currency: string;
  onSelect?: ((name: string) => void) | undefined;
  onOpenFilter?:
    | ((filter: { label: string; ids: string[]; direct: boolean }) => void)
    | undefined;
  limit?: number;
  figures?: "amount" | "both";
  showMeter?: boolean;
}) {
  const phone = useOverlayMedia();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [pushedId, setPushedId] = useState<string | null>(null);
  const ranked = groups ?? categories.map((item) => flatGroup(item));
  const total = ranked.reduce((sum, item) => sum + item.cents, 0);
  useEffect(() => {
    function onPop() {
      setPushedId(null);
    }
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
    };
  }, []);
  if (ranked.length === 0) {
    return <p className="empty">No confirmed Expenses in this month yet.</p>;
  }
  const pushed = ranked.find((item) => item.id === pushedId) ?? null;
  if (phone && pushed !== null) {
    return (
      <div className="cat-drill">
        <button
          className="cat-drill-back"
          type="button"
          onClick={() => {
            if (window.history.state?.catDrill === pushed.id) {
              window.history.back();
              return;
            }
            setPushedId(null);
          }}
        >
          ← {pushed.name}
        </button>
        <Breakdown
          group={pushed}
          currency={currency}
          figures={figures}
          onSelect={onSelect}
          onOpenFilter={onOpenFilter}
        />
      </div>
    );
  }
  const visible =
    limit === undefined ? ranked : ranked.slice(0, Math.max(0, limit));
  const hidden = ranked.length - visible.length;
  return (
    <div className={`cat-list${figures === "amount" ? " is-amount" : ""}`}>
      {visible.map((item) => {
        const expandable = item.children.length > 0;
        const open = expandedId === item.id && !phone;
        const share = total === 0 ? 0 : Math.round((item.cents / total) * 100);
        return (
          <div className="cat-block" key={item.id}>
            <RankRow
              name={item.name}
              cents={item.cents}
              share={share}
              currency={currency}
              figures={figures}
              showMeter={showMeter}
              provisional={item.provisional}
              expandable={expandable}
              expanded={open}
              onClick={() => {
                if (!expandable) {
                  onSelect?.(item.name);
                  return;
                }
                if (phone) {
                  window.history.pushState({ catDrill: item.id }, "");
                  setPushedId(item.id);
                  return;
                }
                setExpandedId((current) =>
                  current === item.id ? null : item.id,
                );
              }}
              onKeyDown={(event) => {
                if (!expandable || phone) {
                  return;
                }
                if (event.key === "ArrowRight" || event.key === "Enter") {
                  event.preventDefault();
                  setExpandedId(item.id);
                }
                if (event.key === "ArrowLeft") {
                  event.preventDefault();
                  setExpandedId(null);
                }
              }}
            />
            {open ? (
              <Breakdown
                group={item}
                currency={currency}
                figures={figures}
                onSelect={onSelect}
                onOpenFilter={onOpenFilter}
              />
            ) : null}
          </div>
        );
      })}
      {hidden > 0 ? <p className="cat-more">{hidden} more</p> : null}
    </div>
  );
}

function Breakdown({
  group,
  currency,
  figures,
  onSelect,
  onOpenFilter,
}: {
  group: SpendGroup;
  currency: string;
  figures: "amount" | "both";
  onSelect?: ((name: string) => void) | undefined;
  onOpenFilter?:
    | ((filter: { label: string; ids: string[]; direct: boolean }) => void)
    | undefined;
}) {
  const ids = [
    group.id,
    ...group.children
      .map((child) => child.categoryId)
      .filter((id): id is string => id !== null),
  ];
  return (
    <div className="cat-breakdown">
      {onOpenFilter !== undefined ? (
        <div className="cat-breakdown-filters">
          <button
            className="chip"
            type="button"
            onClick={() => {
              onOpenFilter({ label: group.name, ids, direct: false });
            }}
          >
            {group.name}
          </button>
          <button
            className="chip"
            type="button"
            onClick={() => {
              onOpenFilter({
                label: `${group.name} direct`,
                ids: [group.id],
                direct: true,
              });
            }}
          >
            Only direct
          </button>
        </div>
      ) : null}
      {group.children.map((child) => {
        const share =
          group.cents === 0 ? 0 : Math.round((child.cents / group.cents) * 100);
        return (
          <RankRow
            key={child.id}
            name={child.name}
            parentName={child.unsorted ? null : group.name}
            cents={child.cents}
            share={share}
            currency={currency}
            figures={figures}
            showMeter
            provisional={child.provisional}
            expandable={false}
            expanded={false}
            nested
            muted={child.unsorted}
            onClick={() => {
              if (onOpenFilter !== undefined) {
                onOpenFilter(
                  child.unsorted
                    ? {
                        label: `${group.name} direct`,
                        ids: [group.id],
                        direct: true,
                      }
                    : {
                        label: child.name,
                        ids:
                          child.categoryId === null ? [] : [child.categoryId],
                        direct: false,
                      },
                );
                return;
              }
              onSelect?.(child.unsorted ? group.name : child.name);
            }}
          />
        );
      })}
    </div>
  );
}

function RankRow({
  name,
  parentName = null,
  cents,
  share,
  currency,
  figures,
  showMeter,
  provisional,
  expandable,
  expanded,
  nested = false,
  muted = false,
  onClick,
  onKeyDown,
}: {
  name: string;
  parentName?: string | null;
  cents: number;
  share: number;
  currency: string;
  figures: "amount" | "both";
  showMeter: boolean;
  provisional: boolean;
  expandable: boolean;
  expanded: boolean;
  nested?: boolean;
  muted?: boolean;
  onClick: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  const color = categoryColor(categoryPrimary(parentName ?? name));
  const row = (
    <>
      <CategoryChip name={name} parentName={nested ? parentName : null} />
      {showMeter ? (
        <span
          className="cat-meter"
          style={{ "--cat-color": color } as CSSProperties}
        >
          <i style={{ width: `${share}%` }} />
        </span>
      ) : null}
      <span className="cat-figures">
        {figures === "both" ? (
          <span className="cat-share">{share}%</span>
        ) : null}
        {provisional ? (
          <i
            className="provisional-dot"
            title="Provisional"
            aria-label="Provisional"
          />
        ) : null}
        <span className="amount">
          <MoneyText text={formatUnsigned(centsToMoney(cents, currency))} />
        </span>
      </span>
    </>
  );
  return (
    <button
      className={`cat-row${showMeter ? "" : " is-plain"}${nested ? " is-child" : ""}${muted ? " is-muted" : ""}`}
      type="button"
      aria-expanded={expandable ? expanded : undefined}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      {row}
    </button>
  );
}

function flatGroup(item: { name: string; cents: number }): SpendGroup {
  return {
    id: item.name,
    name: item.name,
    cents: item.cents,
    directCents: item.cents,
    provisional: false,
    children: [],
  };
}
