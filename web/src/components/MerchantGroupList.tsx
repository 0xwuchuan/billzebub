import { useState } from "react";

import type { Category } from "../api";
import type { MerchantGroupView } from "../lib/merchantGroups";
import { formatUnsigned } from "../lib/money";
import { Button } from "./ui/Button";
import { MoneyText } from "./MoneyText";

export type MerchantUndo = {
  label: string;
  categoryName: string;
  count: number;
};

export type MerchantApplyRequest = {
  normalizedKey: string;
  label: string;
  categoryId: string;
  etag: string;
  included: { transactionId: string; version: number }[];
  excludedIds: string[];
};

export function MerchantGroupList({
  groups,
  categories,
  undo,
  saving,
  onApply,
  onUndo,
}: {
  groups: MerchantGroupView[];
  categories: Category[];
  undo: MerchantUndo | null;
  saving: boolean;
  onApply: (request: MerchantApplyRequest) => void;
  onUndo: () => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [excluded, setExcluded] = useState<Record<string, string[]>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  if (groups.length === 0 && undo === null) {
    return null;
  }
  const choices = categories.filter(
    (category) => category.active && category.name !== "Uncategorized",
  );

  return (
    <section className="merchant-groups" aria-label="Merchant groups">
      {undo === null ? null : (
        <div className="card merchant-undo" role="status">
          <p>
            Applied {undo.categoryName} to {undo.count} {undo.label}{" "}
            {undo.count === 1 ? "charge" : "charges"}, including future ones.
          </p>
          <Button variant="outline" onClick={onUndo} disabled={saving}>
            Undo
          </Button>
        </div>
      )}
      {groups.map((group) => {
        const excludedIds = new Set(excluded[group.normalizedKey] ?? []);
        const included = group.members.filter(
          (member) => !excludedIds.has(member.transactionId),
        );
        const categoryId = drafts[group.normalizedKey] ?? "";
        const open = expanded === group.normalizedKey;
        return (
          <article key={group.normalizedKey} className="card merchant-group">
            <div className="merchant-group-head">
              <div>
                <h2>{group.label}</h2>
                <p className="muted">{group.members.length} pending</p>
              </div>
              <div className="merchant-group-actions">
                <label className="merchant-category">
                  <span className="sr-only">Category for {group.label}</span>
                  <select
                    value={categoryId}
                    onChange={(event) => {
                      const value = event.target.value;
                      setDrafts((current) => ({
                        ...current,
                        [group.normalizedKey]: value,
                      }));
                    }}
                  >
                    <option value="">Category</option>
                    {choices.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="primary"
                  disabled={
                    saving || categoryId === "" || included.length === 0
                  }
                  onClick={() => {
                    onApply({
                      normalizedKey: group.normalizedKey,
                      label: group.label,
                      categoryId,
                      etag: group.etag,
                      included: included.map((member) => ({
                        transactionId: member.transactionId,
                        version: member.version,
                      })),
                      excludedIds: [...excludedIds],
                    });
                  }}
                >
                  Apply to all {included.length} + future
                </Button>
                <Button
                  variant="ghost"
                  aria-expanded={open}
                  onClick={() => {
                    setExpanded(open ? null : group.normalizedKey);
                  }}
                >
                  Exclude
                </Button>
              </div>
            </div>
            {open ? (
              <ul className="merchant-exclude">
                {group.members.map((member) => {
                  const checked = !excludedIds.has(member.transactionId);
                  return (
                    <li key={member.transactionId}>
                      <label>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => {
                            setExcluded((current) => {
                              const prior = new Set(
                                current[group.normalizedKey] ?? [],
                              );
                              if (prior.has(member.transactionId)) {
                                prior.delete(member.transactionId);
                              } else {
                                prior.add(member.transactionId);
                              }
                              return {
                                ...current,
                                [group.normalizedKey]: [...prior],
                              };
                            });
                          }}
                        />
                        <span>{member.counterparty}</span>
                        <span className="amount">
                          {member.amount === "" ? null : (
                            <MoneyText
                              text={formatUnsigned({
                                amount: member.amount,
                                currency: member.currency || "SGD",
                              })}
                            />
                          )}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
