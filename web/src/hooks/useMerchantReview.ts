import { useCallback, useEffect, useMemo, useState } from "react";

import {
  applyMerchantGroup,
  listMerchantGroups,
  listMerchantRules,
  undoMerchantGroup,
  type Category,
  type MerchantRule,
  type Review,
  type Transaction,
} from "../api";
import type { FixtureMode } from "../dev/fixtureMode";
import {
  merchantGroupsFromReviews,
  type MerchantGroupView,
} from "../lib/merchantGroups";
import type {
  MerchantApplyRequest,
  MerchantUndo,
} from "../components/MerchantGroupList";

type UndoRecord = {
  banner: MerchantUndo;
  normalizedKey: string;
  categoryId: string;
  etag: string;
  transactions: { transaction_id: string; version: number }[];
  excludedIds: string[];
  previousRules: MerchantRule[];
};

export function useMerchantReview({
  reviews,
  transactions,
  categories,
  fixtureMode,
  reload,
}: {
  reviews: Review[];
  transactions: Transaction[];
  categories: Category[];
  fixtureMode: FixtureMode | null;
  reload: () => Promise<void>;
}) {
  const fixture = import.meta.env.DEV && fixtureMode !== null;
  const [rules, setRules] = useState<MerchantRule[]>([]);
  const [rulesMode, setRulesMode] = useState<FixtureMode | null>(null);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const [hiddenMode, setHiddenMode] = useState<FixtureMode | null>(null);
  const [undo, setUndo] = useState<UndoRecord | null>(null);
  const [undoMode, setUndoMode] = useState<FixtureMode | null>(null);
  const [saving, setSaving] = useState(false);
  const [remoteGroups, setRemoteGroups] = useState<MerchantGroupView[] | null>(
    null,
  );
  const activeRules =
    fixture && rulesMode !== fixtureMode ? seedRules(fixtureMode) : rules;
  const activeUndo = fixture && undoMode !== fixtureMode ? null : undo;
  const suppressedReviewIds = useMemo(
    () => (fixture && hiddenMode !== fixtureMode ? [] : hiddenIds),
    [fixture, fixtureMode, hiddenIds, hiddenMode],
  );

  const localGroups = useMemo(() => {
    return merchantGroupsFromReviews(
      reviews.filter((review) => !suppressedReviewIds.includes(review.id)),
      transactions,
    );
  }, [reviews, suppressedReviewIds, transactions]);

  const refreshRemote = useCallback(async () => {
    if (fixture) {
      return;
    }
    const [groupPage, rulePage] = await Promise.all([
      listMerchantGroups(),
      listMerchantRules(),
    ]);
    setRemoteGroups(groupPage.items.map(remoteGroup));
    setRules(rulePage.items);
  }, [fixture]);

  useEffect(() => {
    if (fixture) {
      return;
    }
    let active = true;
    void Promise.all([listMerchantGroups(), listMerchantRules()])
      .then(([groupPage, rulePage]) => {
        if (!active) {
          return;
        }
        setRemoteGroups(groupPage.items.map(remoteGroup));
        setRules(rulePage.items);
      })
      .catch(() => {
        if (active) {
          setRemoteGroups(null);
        }
      });
    return () => {
      active = false;
    };
  }, [fixture]);

  async function applyGroup(request: MerchantApplyRequest): Promise<void> {
    const category = categories.find((item) => item.id === request.categoryId);
    const categoryName = category?.name ?? "Category";
    setSaving(true);
    try {
      const reviewIds = request.included
        .map(
          (item) =>
            localGroups
              .flatMap((group) => group.members)
              .find((member) => member.transactionId === item.transactionId)
              ?.reviewId,
        )
        .filter((id): id is string => id !== undefined);
      setHiddenMode(fixtureMode);
      setHiddenIds((current) => [
        ...(hiddenMode === fixtureMode ? current : []),
        ...reviewIds,
      ]);
      if (fixture) {
        setRulesMode(fixtureMode);
        setRules((current) => {
          const base =
            rulesMode === fixtureMode ? current : seedRules(fixtureMode);
          const next = base.filter(
            (rule) => rule.normalized_key !== request.normalizedKey,
          );
          return [
            {
              normalized_key: request.normalizedKey,
              label: request.label,
              category_id: request.categoryId,
              category_name: categoryName,
              source: "owner" as const,
            },
            ...next,
          ];
        });
        setUndo({
          banner: {
            label: request.label,
            categoryName,
            count: request.included.length,
          },
          normalizedKey: request.normalizedKey,
          categoryId: request.categoryId,
          etag: "fixture-undo",
          transactions: request.included.map((item) => ({
            transaction_id: item.transactionId,
            version: item.version + 1,
          })),
          excludedIds: request.excludedIds,
          previousRules: activeRules,
        });
        setUndoMode(fixtureMode);
        return;
      }
      const applied = await applyMerchantGroup({
        normalizedKey: request.normalizedKey,
        categoryId: request.categoryId,
        excludeTransactionIds: request.excludedIds,
        etag: request.etag,
      });
      setUndo({
        banner: {
          label: applied.label,
          categoryName,
          count: applied.applied.length,
        },
        normalizedKey: applied.normalized_key,
        categoryId: applied.category_id,
        etag: applied.undo_etag,
        transactions: applied.applied,
        excludedIds: applied.excluded_transaction_ids,
        previousRules: activeRules,
      });
      setUndoMode(fixtureMode);
      await reload();
      await refreshRemote();
    } finally {
      setSaving(false);
    }
  }

  async function undoApply(): Promise<void> {
    if (undo === null) {
      return;
    }
    setSaving(true);
    try {
      if (fixture) {
        setHiddenMode(fixtureMode);
        setHiddenIds([]);
        setRulesMode(fixtureMode);
        setRules(undo.previousRules);
        setUndoMode(fixtureMode);
        setUndo(null);
        return;
      }
      await undoMerchantGroup({
        normalizedKey: undo.normalizedKey,
        categoryId: undo.categoryId,
        transactions: undo.transactions,
        excludedTransactionIds: undo.excludedIds,
        etag: undo.etag,
      });
      setUndo(null);
      await reload();
      await refreshRemote();
    } finally {
      setSaving(false);
    }
  }

  return {
    groups: fixture ? localGroups : (remoteGroups ?? localGroups),
    rules: activeRules,
    suppressedReviewIds,
    undo: activeUndo?.banner ?? null,
    saving,
    applyGroup,
    undoApply,
  };
}

function remoteGroup(group: {
  normalized_key: string;
  label: string;
  etag: string;
  transactions: {
    review_id: string;
    transaction_id: string;
    version: number;
    counterparty: string;
    amount: string;
    currency: string;
    effective_date: string;
  }[];
}): MerchantGroupView {
  return {
    normalizedKey: group.normalized_key,
    label: group.label,
    etag: group.etag,
    members: group.transactions.map((item) => ({
      reviewId: item.review_id,
      transactionId: item.transaction_id,
      version: item.version,
      counterparty: item.counterparty,
      amount: item.amount,
      currency: item.currency,
      effectiveDate: item.effective_date,
    })),
  };
}

function seedRules(mode: FixtureMode | null): MerchantRule[] {
  if (
    !import.meta.env.DEV ||
    mode === null ||
    mode === "empty" ||
    mode === "one"
  ) {
    return [];
  }
  return [
    {
      normalized_key: "example transit",
      label: "Example Transit",
      category_id: "example-cat-transport",
      category_name: "Transport",
      source: "owner",
    },
    {
      normalized_key: "example cafe",
      label: "Example Cafe",
      category_id: "example-cat-dining",
      category_name: "Dining",
      source: "jev",
    },
  ];
}
