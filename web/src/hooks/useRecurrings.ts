import { useCallback, useEffect, useState } from "react";

import {
  createRecurring,
  dismissRecurring,
  getProposedRecurrings,
  getRecurringSummary,
  getRecurrings,
  updateRecurring,
  type RecurringCreateInput,
  type RecurringPatch,
  type RecurringSeries,
  type RecurringSummary,
} from "../api";
import { useFixtureMode } from "../dev/fixtureMode";
import { messageFor } from "../lib/labels";

export function useRecurrings() {
  const [proposed, setProposed] = useState<RecurringSeries[]>([]);
  const [active, setActive] = useState<RecurringSeries[]>([]);
  const [paused, setPaused] = useState<RecurringSeries[]>([]);
  const [summary, setSummary] = useState<RecurringSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fixtureMode = useFixtureMode();

  const reload = useCallback(async () => {
    if (import.meta.env.DEV && fixtureMode !== null) {
      const { recurringsFor } = await import("../dev/worstCaseFixture");
      const fixture = recurringsFor(fixtureMode);
      setProposed(fixture.proposed);
      setActive(fixture.active);
      setPaused(fixture.paused);
      setSummary(fixture.summary);
      setError(null);
      return;
    }
    const [proposedPage, activePage, pausedPage, nextSummary] =
      await Promise.all([
        getProposedRecurrings(),
        getRecurrings("active"),
        getRecurrings("paused"),
        getRecurringSummary(3),
      ]);
    setProposed(proposedPage.items);
    setActive(activePage.items);
    setPaused(pausedPage.items);
    setSummary(nextSummary);
    setError(null);
  }, [fixtureMode]);

  useEffect(() => {
    let activeRequest = true;
    const pending =
      import.meta.env.DEV && fixtureMode !== null
        ? import("../dev/worstCaseFixture").then(({ recurringsFor }) =>
            recurringsFor(fixtureMode),
          )
        : Promise.all([
            getProposedRecurrings(),
            getRecurrings("active"),
            getRecurrings("paused"),
            getRecurringSummary(3),
          ]).then(([proposedPage, activePage, pausedPage, nextSummary]) => ({
            proposed: proposedPage.items,
            active: activePage.items,
            paused: pausedPage.items,
            summary: nextSummary,
          }));
    void pending
      .then((fixture) => {
        if (!activeRequest) {
          return;
        }
        setProposed(fixture.proposed);
        setActive(fixture.active);
        setPaused(fixture.paused);
        setSummary(fixture.summary);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (activeRequest) {
          setError(messageFor(requestError));
        }
      })
      .finally(() => {
        if (activeRequest) {
          setLoading(false);
        }
      });
    return () => {
      activeRequest = false;
    };
  }, [fixtureMode]);

  async function run(
    key: string,
    action: () => Promise<unknown>,
  ): Promise<boolean> {
    setSaving(key);
    setError(null);
    try {
      await action();
      await reload();
      return true;
    } catch (requestError) {
      setError(messageFor(requestError));
      return false;
    } finally {
      setSaving(null);
    }
  }

  return {
    proposed,
    active,
    paused,
    summary,
    loading,
    saving,
    error,
    confirm: (seriesId: string, _patch: RecurringPatch) => {
      if (import.meta.env.DEV && fixtureMode !== null) {
        setProposed((current) => {
          const series = current.find((item) => item.id === seriesId);
          if (series !== undefined) {
            setActive((items) => [...items, { ...series, status: "active" }]);
          }
          return current.filter((item) => item.id !== seriesId);
        });
        return Promise.resolve(true);
      }
      return run(seriesId, () =>
        updateRecurring(seriesId, { ..._patch, status: "active" }),
      );
    },
    dismiss: (seriesId: string) => {
      if (import.meta.env.DEV && fixtureMode !== null) {
        setProposed((current) =>
          current.filter((item) => item.id !== seriesId),
        );
        return Promise.resolve(true);
      }
      return run(seriesId, () => dismissRecurring(seriesId));
    },
    update: (seriesId: string, patch: RecurringPatch) => {
      if (import.meta.env.DEV && fixtureMode !== null) {
        const nextStatus = patch.status;
        if (nextStatus === "paused") {
          setActive((items) => {
            const series = items.find((item) => item.id === seriesId);
            if (series !== undefined) {
              setPaused((paused) => [
                ...paused,
                { ...series, status: "paused" },
              ]);
            }
            return items.filter((item) => item.id !== seriesId);
          });
        } else if (nextStatus === "active") {
          setPaused((items) => {
            const series = items.find((item) => item.id === seriesId);
            if (series !== undefined) {
              setActive((active) => [
                ...active,
                { ...series, status: "active" },
              ]);
            }
            return items.filter((item) => item.id !== seriesId);
          });
        } else if (nextStatus === "ended") {
          setActive((items) => items.filter((item) => item.id !== seriesId));
          setPaused((items) => items.filter((item) => item.id !== seriesId));
        }
        return Promise.resolve(true);
      }
      return run(seriesId, () => updateRecurring(seriesId, patch));
    },
    create: (input: RecurringCreateInput) => {
      if (import.meta.env.DEV && fixtureMode !== null) {
        setActive((current) => [
          ...current,
          {
            id: `example-series-local-${current.length}`,
            counterparty: input.counterparty,
            amount: { amount: input.amount, currency: input.currency },
            amount_min: null,
            amount_max: null,
            cadence: input.cadence,
            interval_days: input.interval_days ?? null,
            next_expected_date: input.next_expected_date,
            category_id: input.category_id ?? null,
            primary_account_id: input.primary_account_id ?? null,
            status: "active",
            source: "manual",
            confidence: null,
            last_matched_tx_id: null,
            last_amount: { amount: input.amount, currency: input.currency },
            linked_count: 0,
            missed: false,
            notes: null,
            cluster_key: "example-local",
          },
        ]);
        return Promise.resolve(true);
      }
      return run("create", () => createRecurring(input));
    },
  };
}
